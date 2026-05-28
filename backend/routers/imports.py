import asyncio
import logging
import re
import time
import uuid

log = logging.getLogger(__name__)
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.database import SessionLocal, get_db
from backend.schemas import EmailAccountCreate
from backend.models import EmailAccount, Transaction
from backend.services.ai import extract_from_text, extract_from_image, categorize_vendors, map_csv_columns
from backend.services import rag
from backend.services.email_ingestion import fetch_email_headers, fetch_email_bodies
from backend.services.pdf_ingestion import (
    extract_text_from_pdf,
    is_image_file,
    is_pdf_file,
    normalise_image,
)
from backend.services.csv_ingestion import parse_csv, apply_mapping
from backend.services.vendor_rules import BUILT_IN_RULES, INCOME_CATEGORIES  # noqa: F401
from backend.models import VendorRule

_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}

SYNC_COOLDOWN_MINUTES = 15

router = APIRouter(prefix="/import", tags=["import"])

_jobs: dict[str, dict] = {}

_FINANCIAL_RE = re.compile(
    r"\binvoice\b|\bbill\b|\breceipt\b|\bpayment\b|\bcharge\b|\bpaid\b|\border\b"
    r"|\bsubscription\b|amount due|due date|total due"
    r"|order confirmation|\bstatement\b|\bpayout\b"
    r"|\brefund\b|\bdeposit\b|\bfunds\b",
    re.IGNORECASE,
)
_NON_FINANCIAL_RE = re.compile(
    r"\bdispatched\b|\bshipped\b|\btracking\b|\bdelivered\b"
    r"|\blogistics\b|\bparcel\b|\bshipment\b"
    r"|out for delivery|in transit|is on its way|has left|cleared customs"
    r"|waiting for payment|awaiting payment|complete your payment|complete your purchase"
    r"|your order is waiting|unpaid order|abandoned cart|don't forget to pay"
    r"|\byou.?ve won\b|\byou won\b|\bcongratulations\b|\breward points\b|\bgift card\b|\bgift voucher\b"
    r"|\be-?gift\b|\bloyalty points\b|\bcashback reward\b|\bbonus points\b|\bprize\b"
    r"|lower interest rate|balance transfer|instalment plan offer|credit card offer|cash instalment"
    r"|offer ends|get started today"
    r"|payment declined|payment unsuccessful|payment failed|transaction declined"
    r"|card declined|could not process|unable to process your payment"
    r"|retry payment|update your payment|billing problem|payment issue|payment attempt"
    r"|we were unable to charge|your payment could not"
    r"|\bdeals?\b|\bspecial offer\b|\bflash sale\b|\bexclusive offer\b|\blimited time\b"
    r"|\boff\b.*%|\b\d+%\s*off\b|\bfancy a\b|\bdiscount\b|\bpromo\b|\bsale ends\b"
    r"|\bdon.?t miss\b|\bact now\b|\bhurry\b|\blast chance\b",
    re.IGNORECASE,
)
_IGNORED_SENDERS_RE = re.compile(
    r"@(?:[\w.-]+\.)?glassdoor\.com"
    r"|@(?:[\w.-]+\.)?indeed\.com"
    r"|@(?:[\w.-]+\.)?linkedin\.com",
    re.IGNORECASE,
)

@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _load_category_rules(db) -> list[tuple[str, str]]:
    """Merge user-defined rules (highest priority) with built-in rules, longest-first."""
    user_rules = db.query(VendorRule).all()
    user_pairs = sorted(
        [(r.vendor_pattern.lower().strip(), r.category) for r in user_rules],
        key=lambda x: len(x[0]),
        reverse=True,
    )
    return user_pairs + BUILT_IN_RULES


async def _run_ai_extraction(
    text: str,
    label: str,
    category_rules: list,
) -> dict:
    log.info("AI extracting | %s", label)
    t = time.monotonic()
    try:
        similar = await rag.search(f"{label} {text[:300]}", n_results=5)
    except Exception:
        similar = []
    result = await extract_from_text(text, category_rules=category_rules, similar_transactions=similar)
    log.info("AI done %.1fs | skip=%s vendor=%s amount=%s type=%s | %s",
             time.monotonic() - t, result.get("skip"), result.get("vendor"),
             result.get("amount"), result.get("type"), label)
    return result


def _is_content_duplicate(db: Session, data: dict) -> bool:
    """Return True if an equivalent transaction already exists in the DB."""
    vendor = (data.get("vendor") or "").strip().lower()
    amount = _to_float(data.get("amount"))
    date_val = data.get("date")
    inv = (data.get("invoice_number") or "").strip()
    tx_type = data.get("type") or "expense"

    if inv:
        exists = db.query(Transaction).filter(
            Transaction.invoice_number == inv,
            Transaction.amount == amount,
        ).first()
    else:
        exists = db.query(Transaction).filter(
            Transaction.date == date_val,
            Transaction.amount == amount,
            Transaction.type == tx_type,
        ).first()
        if exists:
            # Extra guard: vendor names can vary slightly; skip only if vendor matches roughly
            existing_vendor = (exists.vendor or "").strip().lower()
            if vendor and existing_vendor and existing_vendor not in vendor and vendor not in existing_vendor:
                exists = None

    return exists is not None


def _to_float(val) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    cleaned = re.sub(r"[^\d.]", "", str(val))
    return float(cleaned) if cleaned else 0.0


def _build_transaction(
    data: dict,
    source: str,
    source_ref: str | None,
    raw_text: str,
    fallback_date: str | None = None,
    fallback_vendor: str | None = None,
    fallback_description: str | None = None,
) -> Transaction:
    is_anomaly = bool(data.get("anomaly"))
    if is_anomaly:
        log.warning("ANOMALY | %s | %s | reason: %s", data.get("vendor"), data.get("amount"), data.get("anomaly_reason"))
    tx_type = data.get("type") or "expense"
    raw_category = data.get("category") or "other"
    if tx_type == "income" and raw_category not in INCOME_CATEGORIES:
        raw_category = "revenue"
    elif tx_type == "expense" and raw_category in INCOME_CATEGORIES:
        raw_category = "other"
    return Transaction(
        date=data.get("date") or fallback_date,
        vendor=data.get("vendor") or fallback_vendor or "",
        amount=_to_float(data.get("amount")),
        tax=_to_float(data.get("tax")),
        category=raw_category,
        type=tx_type,
        source=source,
        source_ref=source_ref,
        description=data.get("description") or fallback_description,
        invoice_number=data.get("invoice_number"),
        raw_text=raw_text,
        anomaly=is_anomaly,
        anomaly_reason=data.get("anomaly_reason"),
    )



async def _index_transactions(transaction_ids: list[int]):
    db = SessionLocal()
    try:
        for tid in transaction_ids:
            t = db.get(Transaction, tid)
            if t:
                try:
                    await rag.index_transaction(t)
                except Exception:
                    pass
    finally:
        db.close()


# ── Email accounts ──────────────────────────────────────────────────────────
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
    accounts = db.query(EmailAccount).all()
    return [_serialize_account(a) for a in accounts]


@router.post("/email-accounts")
def add_email_account(body: EmailAccountCreate, db: Session = Depends(get_db)):
    existing = db.query(EmailAccount).filter(EmailAccount.email == body.email).first()
    if existing:
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

# ── Email sync ─────────────────────────────────────────────────────────────
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
        for tid in email_ids:
            rag.remove_transaction(tid)
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

    # Stage 1: fetch headers only
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
        # Stage 2: subject-level financial filter
        candidate_headers = [h for h in all_headers if _looks_financial(h)]
        log.info("EMAIL SYNC | subject-filter passed=%d  dropped=%d", len(candidate_headers), len(all_headers) - len(candidate_headers))

        # Stage 3: dedup — skip UIDs already in DB
        t1 = time.monotonic()
        new_headers = [
            h for h in candidate_headers
            if not db.query(Transaction).filter(
                Transaction.source_ref == f"{account_id}:{h['uid']}"
            ).first()
        ]
        log.info("TIMING | dedup check: %.1fs | new=%d  already_imported=%d", time.monotonic() - t1, len(new_headers), len(candidate_headers) - len(new_headers))

        # Stage 4: fetch full bodies only for new financial emails
        t2 = time.monotonic()
        try:
            emails = await loop.run_in_executor(
                None, lambda: fetch_email_bodies(**imap_kwargs, headers=new_headers)
            )
        except Exception as e:
            _jobs[job_id] = {"status": "failed", "error": str(e)}
            return
        log.info("TIMING | IMAP bodies: %.1fs", time.monotonic() - t2)

        # Stage 5: full financial filter now that we have body content
        financial_emails = [em for em in emails if _looks_financial(em)]
        log.info("EMAIL SYNC | body-filter passed=%d  dropped=%d", len(financial_emails), len(emails) - len(financial_emails))

        category_rules = _load_category_rules(db)
        sem = asyncio.Semaphore(3)

        errors = []
        skipped_count = 0
        added_transactions: list[Transaction] = []
        tasks = [asyncio.create_task(_extract_email(em, sem, category_rules)) for em in financial_emails]
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
                log.info("AI SKIP (duplicate) | %s | %s | $%s", data.get("vendor"), data.get("date"), data.get("amount"))
                skipped_count += 1
                continue
            t = _build_transaction(
                data,
                source="email",
                source_ref=f"{account_id}:{em['uid']}",
                raw_text=em["raw_text"],
                fallback_date=em["date"][:10],
                fallback_vendor=em["from"],
                fallback_description=em["subject"],
            )
            log.info("SAVED | %s | %s | %s $%s", t.type, t.vendor, t.date, t.amount)
            db.add(t)
            db.commit()
            db.refresh(t)
            added_transactions.append(t)
            _jobs[job_id] = {"status": "running", "added": len(added_transactions), "total": len(financial_emails)}

        log.info("TIMING | all AI calls: %.1fs  (%.1fs/email avg)", time.monotonic() - t2, (time.monotonic() - t2) / max(len(financial_emails), 1))

        account = db.get(EmailAccount, account_id)
        if account:
            account.last_synced = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()

        added = len(added_transactions)
        pre_filtered = len(emails) - len(financial_emails)
        log.info("TIMING | total sync: %.1fs  added=%d", time.monotonic() - t0, added)
        transaction_ids = [t.id for t in added_transactions]
        _jobs[job_id] = {
            "status": "done",
            "added": added,
            "skipped": len(emails) - added - len(errors),
            "not_financial": skipped_count + pre_filtered,
            "errors": errors,
        }
        asyncio.create_task(_index_transactions(transaction_ids))
    except Exception as e:
        _jobs[job_id] = {"status": "failed", "error": str(e)}
    finally:
        db.close()


async def _extract_email(
    em: dict,
    sem: asyncio.Semaphore,
    category_rules: list,
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
                elif att["mime_type"] in _IMAGE_MIMES:
                    image_text = await extract_from_image(normalise_image(att["bytes"]))
                    if image_text.strip():
                        text = image_text
                        break
            label = f"{em.get('from', '')} | {em.get('subject', '').replace(chr(10), ' ')}"
            result = await _run_ai_extraction(text, label, category_rules)
            return em, result, None
        except Exception as e:
            log.warning("AI error | %s\n  → %s: %s", em.get("subject", "").replace("\n", " "), type(e).__name__, e)
            return em, None, str(e)


def _looks_financial(em: dict) -> bool:
    sender = em.get("from") or ""
    subject = em.get("subject") or ""
    if _IGNORED_SENDERS_RE.search(sender):
        return False
    text = (em.get("raw_text") or "")[:2000]
    combined = subject + " " + text
    if _NON_FINANCIAL_RE.search(subject):
        return False
    if not _FINANCIAL_RE.search(combined):
        return False
    log.info("PASS | %s | %s", sender, subject)
    return True

# ── File upload ──────────────────────────────────────────────────────────────

@router.post("/file")
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    filename = file.filename or ""
    file_bytes = await file.read()

    if not is_pdf_file(filename) and not is_image_file(filename):
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload a PDF or image.")

    category_rules = _load_category_rules(db)
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running"}
    asyncio.create_task(_run_file_extraction(job_id, file_bytes, filename, category_rules))
    return {"job_id": job_id, "status": "running"}


async def _run_file_extraction(job_id: str, file_bytes: bytes, filename: str, category_rules: list):
    try:
        if is_pdf_file(filename):
            raw_text = extract_text_from_pdf(file_bytes)
            source = "pdf"
        else:
            raw_text = await extract_from_image(normalise_image(file_bytes))
            source = "image"

        if not raw_text.strip():
            _jobs[job_id] = {"status": "failed", "error": "Could not extract text from file."}
            return

        data = await _run_ai_extraction(raw_text, filename, category_rules)
        if not _to_float(data.get("amount")):
            _jobs[job_id] = {"status": "failed", "error": "Could not extract a non-zero amount from file."}
            return

        db = SessionLocal()
        try:
            t = _build_transaction(data, source=source, source_ref=filename, raw_text=raw_text)
            db.add(t)
            db.commit()
            db.refresh(t)
            transaction = {"id": t.id, "date": t.date, "vendor": t.vendor,
                           "amount": t.amount, "tax": t.tax, "category": t.category, "type": t.type}
        finally:
            db.close()

        asyncio.create_task(_index_transactions([transaction["id"]]))
        _jobs[job_id] = {"status": "done", "added": 1, "skipped": 0, "transaction": transaction}
    except Exception as e:
        _jobs[job_id] = {"status": "failed", "error": str(e)}

# --- csv -----------------------
@router.post("/csv")
async def upload_csv(file: UploadFile = File(...)):
    file_bytes = await file.read()
    filename = file.filename or "upload.csv"

    try:
        headers, rows = parse_csv(file_bytes, filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")
    if not headers:
        raise HTTPException(status_code=400, detail="File has no headers.")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running"}
    asyncio.create_task(_run_csv(job_id, headers, rows, filename))
    return {"job_id": job_id, "status": "running"}


async def _run_csv(job_id: str, headers: list, rows: list, filename: str):
    try:
        mapping = await map_csv_columns(headers, rows[:5])
        log.info("CSV MAPPING | %s", mapping)
        transactions = apply_mapping(rows, mapping)
        log.info("CSV APPLY | rows=%d  transactions=%d", len(rows), len(transactions))
        if not transactions:
            _jobs[job_id] = {"status": "failed", "error": "No valid transactions found in file."}
            return

        db = SessionLocal()
        try:
            category_rules = _load_category_rules(db)

            # Ask AI to categorize: real vendor names without a CSV category, plus
            # descriptions for rows where the vendor is Unknown.
            to_categorize = set()
            for tx in transactions:
                csv_category = tx.get("category") or ""
                if csv_category and csv_category != "other":
                    continue
                if tx["vendor"] != "Unknown":
                    to_categorize.add(tx["vendor"])
                elif tx.get("description"):
                    to_categorize.add(tx["description"]) # some statements put the vendor name in the description column, so use that as a fallback if vendor is Unknown
            vendor_categories = await categorize_vendors(list(to_categorize), category_rules=category_rules)

            added = 0
            for tx in transactions:
                csv_category = tx.get("category") or ""
                if csv_category and csv_category != "other":
                    category = csv_category
                elif tx["vendor"] != "Unknown":
                    category = vendor_categories.get(tx["vendor"]) or "other"
                else:
                    category = vendor_categories.get(tx.get("description", "")) or "other"
                data = {**tx, "category": category}
                t = _build_transaction(data, source="csv", source_ref=filename, raw_text="")
                db.add(t)
                added += 1
            db.commit()
            transaction_ids = [
                t.id for t in db.query(Transaction).filter(Transaction.source_ref == filename).all()
            ]
        finally:
            db.close()

        _jobs[job_id] = {"status": "done", "added": added, "skipped": len(rows) - added}
        asyncio.create_task(_index_transactions(transaction_ids))
    except Exception as e:
        _jobs[job_id] = {"status": "failed", "error": str(e)}
