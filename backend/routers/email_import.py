import asyncio
import logging
import re
import time
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import SessionLocal, get_db
from backend.schemas import EmailAccountCreate
from backend.models import Attachment, EmailAccount, Transaction
from backend.services import rag
from backend.services.extraction_agent import extract_from_image, extract_from_text
from backend.services.email_ingestion import fetch_email_headers, fetch_email_bodies
from backend.services.file_ingestion import extract_text_from_pdf, normalise_image
from backend.routers._import_helpers import (
    _jobs,
    _is_content_duplicate, _to_float, _build_transaction, _index_transactions,
)

log = logging.getLogger(__name__)

_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}
SYNC_COOLDOWN_MINUTES = 15

router = APIRouter(prefix="/import", tags=["import"])

_FINANCIAL_RE = re.compile(
    r"\binvoice\b|\bbill\b|\breceipt\b|\bpayment\b|\bcharge\b|\bpaid\b|\border\b"
    r"|\bsubscription\b|amount due|due date|total due"
    r"|order confirmation|\bstatement\b|\bpayout\b"
    r"|\brefund\b|\bdeposit\b|\bfunds\b",
    re.IGNORECASE,
)
_NON_FINANCIAL_RE = re.compile(
    "|".join([
        # Shipping / logistics
        r"\bdispatched\b", r"\bshipped\b", r"\btracking\b", r"\bdelivered\b",
        r"\blogistics\b", r"\bparcel\b", r"\bshipment\b",
        r"out for delivery", r"in transit", r"is on its way", r"has left", r"cleared customs",
        # Unpaid / pending (not yet a real transaction)
        r"waiting for payment", r"awaiting payment", r"complete your payment", r"complete your purchase",
        r"your order is waiting", r"unpaid order", r"abandoned cart", r"don't forget to pay",
        # Rewards and non-cash promotions
        r"\byou.?ve won\b", r"\byou won\b", r"\bcongratulations\b",
        r"\breward points\b", r"\bgift card\b", r"\bgift voucher\b", r"\be-?gift\b",
        r"\bloyalty points\b", r"\bcashback reward\b", r"\bbonus points\b", r"\bprize\b",
        # Financing / credit offers
        r"lower interest rate", r"balance transfer", r"instalment plan offer",
        r"credit card offer", r"cash instalment", r"offer ends", r"get started today",
        # Failed / declined payments
        r"payment declined", r"payment unsuccessful", r"payment failed", r"transaction declined",
        r"card declined", r"could not process", r"unable to process your payment",
        r"retry payment", r"update your payment", r"billing problem",
        r"payment issue", r"payment attempt", r"we were unable to charge", r"your payment could not",
        # Account / statement notifications (no transaction occurred)
        r"statement\s+is\s+(now\s+)?ready", r"statement\s+is\s+now\s+available",
        r"your\s+(online\s+)?statement\s+is", r"your\s+account\s+statement",
        r"account\s+activity\s+(summary|update|notification)",
        r"your\s+balance\s+is", r"available\s+balance",
        r"password\s+reset", r"login\s+(alert|notification)", r"sign.?in\s+(alert|attempt)",
        # Promotional / marketing
        r"\bdeals?\b", r"\bspecial offer\b", r"\bflash sale\b", r"\bexclusive offer\b",
        r"\blimited time\b", r"\b\d+%\s*off\b", r"\bfancy a\b",
        r"\bdiscount\b", r"\bpromo\b", r"\bsale ends\b",
        r"\bdon.?t miss\b", r"\bact now\b", r"\bhurry\b", r"\blast chance\b",
    ]),
    re.IGNORECASE,
)
_IGNORED_SENDERS_RE = re.compile(
    r"@(?:[\w.-]+\.)?glassdoor\.com"
    r"|@(?:[\w.-]+\.)?indeed\.com"
    r"|@(?:[\w.-]+\.)?linkedin\.com",
    re.IGNORECASE,
)


# ── Email accounts ─────────────────────────────────────────────────────────────

def _serialize_account(a: EmailAccount) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "email": a.email,
        "imap_host": a.imap_host,
        "imap_port": a.imap_port,
        "username": a.username,
        "last_synced": a.last_synced.isoformat() if a.last_synced else None,
    }


@router.get("/email-accounts")
def list_email_accounts(db: Session = Depends(get_db)):
    return [_serialize_account(a) for a in db.query(EmailAccount).all()]


@router.post("/email-accounts")
def add_email_account(body: EmailAccountCreate, db: Session = Depends(get_db)):
    if db.query(EmailAccount).filter(EmailAccount.email == body.email).first():
        raise HTTPException(status_code=400, detail="Account already exists")
    account = EmailAccount(**body.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    return _serialize_account(account)


@router.delete("/email-accounts/{account_id}")
def delete_email_account(account_id: int, db: Session = Depends(get_db)):
    account = db.get(EmailAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    db.delete(account)
    db.commit()
    return {"ok": True}


# ── Email sync ─────────────────────────────────────────────────────────────────

def aus_fy_start(today: date | None = None) -> date:
    """Return 1 July of the current Australian financial year."""
    d = today or date.today()
    return date(d.year, 7, 1) if d.month >= 7 else date(d.year - 1, 7, 1)


@router.post("/email-accounts/{account_id}/sync")
async def sync_email_account(
    account_id: int,
    reimport: bool = False,
    db: Session = Depends(get_db),
):
    account = db.get(EmailAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if not reimport and account.last_synced:
        elapsed = datetime.now(timezone.utc).replace(tzinfo=None) - account.last_synced
        if elapsed < timedelta(minutes=SYNC_COOLDOWN_MINUTES):
            remaining = int((timedelta(minutes=SYNC_COOLDOWN_MINUTES) - elapsed).total_seconds())
            raise HTTPException(status_code=429, detail=f"Sync cooldown active — try again in {remaining}s")

    if reimport:
        email_ids = [row.id for row in db.query(Transaction.id).filter(Transaction.source == "email").all()]
        if email_ids:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: rag._col.delete(ids=[str(i) for i in email_ids]))
        db.query(Transaction).filter(Transaction.source == "email").delete()
        db.commit()

    since = aus_fy_start() if (reimport or not account.last_synced) else account.last_synced.date()
    days_back = (date.today() - since).days + 1

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running", "added": 0, "skipped": 0, "errors": []}

    asyncio.create_task(_run_email_sync(
        job_id=job_id,
        account_id=account_id,
        imap_host=account.imap_host,
        imap_port=account.imap_port,
        username=account.username,
        password=account.password,
        days_back=days_back,
    ))

    return {"job_id": job_id, "status": "running", "days_back": days_back}


async def _run_email_sync(
    job_id: str,
    account_id: int,
    imap_host: str,
    imap_port: int,
    username: str,
    password: str,
    days_back: int,
):
    loop = asyncio.get_event_loop()
    imap_kwargs = dict(host=imap_host, port=imap_port, username=username, password=password)

    t0 = time.monotonic()
    try:
        all_headers = await loop.run_in_executor(
            None, lambda: fetch_email_headers(**imap_kwargs, days_back=days_back)
        )
    except Exception as e:
        _jobs[job_id] = {"status": "failed", "error": str(e)}
        return
    log.info("TIMING | IMAP headers: %.1fs | fetched=%d", time.monotonic() - t0, len(all_headers))

    db = SessionLocal()
    try:
        candidate_headers = [h for h in all_headers if _looks_financial(h)]
        log.info("EMAIL SYNC | subject-filter passed=%d  dropped=%d",
                 len(candidate_headers), len(all_headers) - len(candidate_headers))

        t1 = time.monotonic()
        try:
            emails = await loop.run_in_executor(
                None, lambda: fetch_email_bodies(**imap_kwargs, headers=candidate_headers)
            )
        except Exception as e:
            _jobs[job_id] = {"status": "failed", "error": str(e)}
            return
        log.info("TIMING | IMAP bodies: %.1fs", time.monotonic() - t1)

        financial_emails = [em for em in emails if _looks_financial(em)]
        log.info("EMAIL SYNC | body-filter passed=%d  dropped=%d",
                 len(financial_emails), len(emails) - len(financial_emails))

        sem = asyncio.Semaphore(3)

        errors = []
        skipped_count = 0
        added_transactions: list[Transaction] = []
        tasks = [asyncio.create_task(_extract_email(em, sem)) for em in financial_emails]
        t2 = time.monotonic()

        for coro in asyncio.as_completed(tasks):
            em, data, err = await coro
            if err:
                errors.append({"uid": f"{account_id}:{em['uid']}", "error": err})
                continue
            if not data or data.get("skip"):
                log.info("AI SKIP | %s", em.get("subject", ""))
                skipped_count += 1
                continue
            if not _to_float(data.get("amount")):
                log.info("AI SKIP (zero amount) | %s", em.get("subject", "").replace("\n", " "))
                skipped_count += 1
                continue
            if _is_content_duplicate(db, data):
                log.info("AI SKIP (duplicate) | %s | %s | $%s",
                         data.get("vendor"), data.get("date"), data.get("amount"))
                skipped_count += 1
                continue
            t = _build_transaction(
                data,
                source="email",
                source_ref=f"{account_id}:{em['uid']}",
                raw_text=em.get("extracted_text") or em["raw_text"],
                fallback_date=em["date"] or None,
                fallback_vendor=em["from"],
                fallback_description=em["subject"],
            )
            log.info("SAVED | %s | %s | %s $%s", t.type, t.vendor, t.date, t.amount)
            db.add(t)
            db.commit()
            db.refresh(t)
            for att in em.get("attachments", []):
                if att.get("bytes"):
                    db.add(Attachment(
                        transaction_id=t.id,
                        filename=att.get("filename") or None,
                        mime_type=att["mime_type"],
                        data=att["bytes"],
                    ))
            db.commit()
            added_transactions.append(t)
            asyncio.create_task(_index_transactions([t.id]))
            _jobs[job_id] = {"status": "running", "added": len(added_transactions), "total": len(financial_emails)}

        log.info("TIMING | all AI calls: %.1fs  (%.1fs/email avg)",
                 time.monotonic() - t2, (time.monotonic() - t2) / max(len(financial_emails), 1))

        account = db.get(EmailAccount, account_id)
        if account:
            account.last_synced = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()

        added = len(added_transactions)
        log.info("TIMING | total sync: %.1fs  added=%d", time.monotonic() - t0, added)
        _jobs[job_id] = {
            "status": "done",
            "added": added,
            "skipped": len(emails) - added - len(errors),
            "not_financial": skipped_count + (len(emails) - len(financial_emails)),
            "errors": errors,
        }
    except Exception as e:
        _jobs[job_id] = {"status": "failed", "error": str(e)}
    finally:
        db.close()


async def _extract_email(
    em: dict,
    sem: asyncio.Semaphore,
) -> tuple[dict, dict | None, str | None]:
    async with sem:
        try:
            text = em.get("raw_text") or ""
            for att in em.get("attachments", []):
                if att["mime_type"] == "application/pdf":
                    pdf_text = extract_text_from_pdf(att["bytes"])
                    if pdf_text.strip():
                        text = pdf_text
                        break
                elif att["mime_type"] in _IMAGE_MIMES and att.get("is_attachment", True):
                    # Skip inline images (logos, icons) — only use explicit file attachments
                    image_text = await extract_from_image(normalise_image(att["bytes"]))
                    if image_text.strip():
                        text = image_text
                        break
            # Store whatever text was actually used for extraction
            em["extracted_text"] = text
            label = f"{em.get('from', '')} | {em.get('subject', '').replace(chr(10), ' ')}"
            log.info("AI extracting | %s", label)
            t = time.monotonic()
            result = await extract_from_text(text)
            log.info("AI done %.1fs | skip=%s vendor=%s amount=%s category=%s | %s",
                     time.monotonic() - t, result.get("skip"), result.get("vendor"),
                     result.get("amount"), result.get("category"), label)
            return em, result, None
        except Exception as e:
            log.warning("AI error | %s\n  → %s: %s",
                        em.get("subject", "").replace("\n", " "), type(e).__name__, e)
            return em, None, str(e)


def _looks_financial(em: dict) -> bool:
    sender = em.get("from") or ""
    subject = em.get("subject") or ""
    if _IGNORED_SENDERS_RE.search(sender):
        return False
    combined = subject + " " + (em.get("raw_text") or "")[:2000]
    if _NON_FINANCIAL_RE.search(subject):
        return False
    if not _FINANCIAL_RE.search(combined):
        return False
    log.info("PASS | %s | %s", sender, subject)
    return True
