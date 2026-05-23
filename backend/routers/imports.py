import asyncio
import logging
import re
import time
import uuid

log = logging.getLogger(__name__)
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import SessionLocal, get_db
from backend.models import EmailAccount, Transaction
from backend.services.ai import extract_transaction, extract_from_image
from backend.services import rag
from backend.services.email_ingestion import fetch_emails
from backend.services.pdf_ingestion import (
    extract_text_from_pdf,
    is_image_file,
    is_pdf_file,
    normalise_image,
)
from backend.services.csv_ingestion import map_columns, parse_csv, apply_mapping  # noqa: F401

_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}

router = APIRouter(prefix="/import", tags=["import"])

_jobs: dict[str, dict] = {}


class EmailAccountCreate(BaseModel):
    name: str
    email: str
    imap_host: str
    imap_port: int = 993
    username: str
    password: str


# ── Email accounts ──────────────────────────────────────────────────────────

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


@router.post("/email-accounts/{account_id}/sync")
async def sync_email_account(
    account_id: int,
    days_back: int = 30,
    reimport: bool = False,
    db: Session = Depends(get_db),
):
    account = db.get(EmailAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if reimport:
        db.query(Transaction).filter(Transaction.source == "email").delete()
        db.commit()

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running", "added": 0, "skipped": 0, "errors": []}

    asyncio.create_task(_run_sync(
        job_id=job_id,
        account_id=account_id,
        imap_host=account.imap_host,
        imap_port=account.imap_port,
        username=account.username,
        password=account.password,
        days_back=days_back,
    ))

    return {"job_id": job_id, "status": "running"}


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _run_sync(
    job_id: str,
    account_id: int,
    imap_host: str,
    imap_port: int,
    username: str,
    password: str,
    days_back: int,
):
    t0 = time.monotonic()
    try:
        loop = asyncio.get_event_loop()
        emails = await loop.run_in_executor(
            None,
            lambda: fetch_emails(
                host=imap_host,
                port=imap_port,
                username=username,
                password=password,
                days_back=days_back,
            ),
        )
    except Exception as e:
        _jobs[job_id] = {"status": "failed", "error": str(e)}
        return
    log.info("TIMING | IMAP fetch: %.1fs", time.monotonic() - t0)

    db = SessionLocal()
    try:
        t1 = time.monotonic()
        new_emails = [
            em for em in emails
            if not db.query(Transaction).filter(Transaction.source_ref == em["uid"]).first()
        ]
        log.info("TIMING | dedup check: %.1fs", time.monotonic() - t1)
        log.info("EMAIL SYNC | fetched=%d  new=%d  already_imported=%d", len(emails), len(new_emails), len(emails) - len(new_emails))

        financial_emails = [em for em in new_emails if _looks_financial(em)]
        log.info("EMAIL SYNC | pre-filter passed=%d  dropped=%d", len(financial_emails), len(new_emails) - len(financial_emails))

        sem = asyncio.Semaphore(3)

        async def _extract(em: dict):
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
                    subject = em.get("subject", "").replace("\n", " ")
                    log.info("AI extracting | %s | %s", em.get("from", ""), subject)
                    t = time.monotonic()
                    result = await extract_transaction(text)
                    log.info("AI done %.1fs | skip=%s vendor=%s amount=%s type=%s | %s",
                             time.monotonic() - t, result.get("skip"), result.get("vendor"),
                             result.get("amount"), result.get("type"), subject)
                    return em, result, None
                except Exception as e:
                    log.warning("AI error | %s\n  → %s: %s", em.get("subject", "").replace("\n", " "), type(e).__name__, e)
                    return em, None, str(e)

        t2 = time.monotonic()
        results = await asyncio.gather(*[_extract(em) for em in financial_emails])
        log.info("TIMING | all AI calls: %.1fs  (%.1fs/email avg)", time.monotonic() - t2, (time.monotonic() - t2) / max(len(financial_emails), 1))

        errors = []
        skipped_count = 0
        added_transactions: list[Transaction] = []
        for em, data, err in results:
            if err:
                errors.append({"uid": em["uid"], "error": err})
                continue
            if not data or data.get("skip"):
                log.info("AI SKIP | %s", em.get("subject", ""))
                skipped_count += 1
                continue
            if not float(data.get("amount") or 0):
                log.info("AI SKIP (zero amount) | %s", em.get("subject", "").replace("\n", " "))
                skipped_count += 1
                continue
            t = Transaction(
                date=data.get("date") or em["date"][:10],
                vendor=data.get("vendor") or em["from"],
                amount=float(data.get("amount") or 0),
                tax=float(data.get("tax") or 0),
                category=data.get("category") or "other",
                type=data.get("type") or "expense",
                source="email",
                source_ref=em["uid"],
                description=data.get("description") or em["subject"],
                invoice_number=data.get("invoice_number"),
                raw_text=em["raw_text"],
            )
            log.info("SAVED | %s | %s | %s $%s", t.type, t.vendor, t.date, t.amount)
            db.add(t)
            added_transactions.append(t)

        account = db.get(EmailAccount, account_id)
        if account:
            account.last_synced = datetime.utcnow()
        db.commit()

        for t in added_transactions:
            db.refresh(t)
            try:
                await rag.index_transaction(t)
            except Exception:
                pass

        added = len(added_transactions)
        pre_filtered = len(new_emails) - len(financial_emails)
        log.info("TIMING | total sync: %.1fs  added=%d", time.monotonic() - t0, added)
        _jobs[job_id] = {
            "status": "done",
            "added": added,
            "skipped": len(emails) - added - len(errors),
            "not_financial": skipped_count + pre_filtered,
            "errors": errors,
        }
    except Exception as e:
        _jobs[job_id] = {"status": "failed", "error": str(e)}
    finally:
        db.close()


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


# ── File upload ──────────────────────────────────────────────────────────────

@router.post("/file")
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    filename = file.filename or ""
    file_bytes = await file.read()

    if is_pdf_file(filename):
        raw_text = extract_text_from_pdf(file_bytes)
        source = "pdf"
    elif is_image_file(filename):
        image_bytes = normalise_image(file_bytes)
        raw_text = await extract_from_image(image_bytes)
        source = "image"
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload a PDF or image.")

    if not raw_text.strip():
        raise HTTPException(status_code=422, detail="Could not extract text from file.")

    data = await extract_transaction(raw_text)
    if not float(data.get("amount") or 0):
        raise HTTPException(status_code=422, detail="Could not extract a non-zero amount from file.")
    t = Transaction(
        date=data.get("date"),
        vendor=data.get("vendor"),
        amount=float(data.get("amount") or 0),
        tax=float(data.get("tax") or 0),
        category=data.get("category") or "other",
        type=data.get("type") or "expense",
        source=source,
        source_ref=filename,
        description=data.get("description"),
        invoice_number=data.get("invoice_number"),
        raw_text=raw_text,
    )
    db.add(t)
    db.commit()
    db.refresh(t)

    asyncio.create_task(_index_transactions([t.id]))

    return {
        "transaction": {
            "id": t.id,
            "date": t.date,
            "vendor": t.vendor,
            "amount": t.amount,
            "tax": t.tax,
            "category": t.category,
            "type": t.type,
        }
    }


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
        mapping = await map_columns(headers, rows[:5])
        transactions = apply_mapping(rows, mapping)
        if not transactions:
            _jobs[job_id] = {"status": "failed", "error": "No valid transactions found in file."}
            return

        db = SessionLocal()
        try:
            added = 0
            for tx in transactions:
                t = Transaction(
                    date=tx["date"],
                    vendor=tx["vendor"],
                    amount=tx["amount"],
                    tax=tx["tax"],
                    type=tx["type"],
                    category=tx["category"],
                    description=tx["description"],
                    invoice_number=tx["invoice_number"],
                    source="csv",
                    source_ref=filename,
                )
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


_FINANCIAL_RE = re.compile(
    r"[\$£€]|\binvoice\b|\bbill\b|\breceipt\b|\bpayment\b|\bcharge\b"
    r"|\bsubscription\b|amount due|due date|total due"
    r"|order confirmation|\bstatement\b|\bpayout\b"
    r"|\brefund\b|\bdeposit\b",
    re.IGNORECASE,
)
_NON_FINANCIAL_RE = re.compile(
    r"\bdispatched\b|\bshipped\b|\btracking\b|\bdelivered\b"
    r"|\blogistics\b|\bparcel\b|\bshipment\b"
    r"|out for delivery|in transit|is on its way|has left|cleared customs",
    re.IGNORECASE,
)
_IGNORED_SENDERS_RE = re.compile(
    r"@(?:[\w.-]+\.)?glassdoor\.com"
    r"|@(?:[\w.-]+\.)?indeed\.com"
    r"|@(?:[\w.-]+\.)?linkedin\.com",
    re.IGNORECASE,
)


def _looks_financial(em: dict) -> bool:
    sender = em.get("from") or ""
    subject = em.get("subject") or ""
    if _IGNORED_SENDERS_RE.search(sender):
        log.info("SKIP (ignored sender) | %s | %s", sender, subject)
        return False
    text = (em.get("raw_text") or "")[:2000]
    combined = subject + " " + text
    if _NON_FINANCIAL_RE.search(subject):
        log.info("SKIP (non-financial subject) | %s | %s", sender, subject)
        return False
    if not _FINANCIAL_RE.search(combined):
        log.info("SKIP (no financial keywords) | %s | %s", sender, subject)
        return False
    log.info("PASS | %s | %s", sender, subject)
    return True


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
