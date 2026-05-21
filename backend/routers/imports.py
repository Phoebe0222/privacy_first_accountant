import asyncio
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
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

router = APIRouter(prefix="/import", tags=["import"])


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
    db: Session = Depends(get_db),
):
    account = db.get(EmailAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        loop = asyncio.get_event_loop()
        emails = await loop.run_in_executor(
            None,
            lambda: fetch_emails(
                host=account.imap_host,
                port=account.imap_port,
                username=account.username,
                password=account.password,
                days_back=days_back,
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Email fetch failed: {e}")

    new_emails = [
        em for em in emails
        if not db.query(Transaction).filter(Transaction.source_ref == em["uid"]).first()
    ]

    sem = asyncio.Semaphore(5)

    async def _extract(em: dict):
        async with sem:
            try:
                return em, await extract_transaction(em["raw_text"]), None
            except Exception as e:
                return em, None, str(e)

    results = await asyncio.gather(*[_extract(em) for em in new_emails])

    errors = []
    added_transactions: list[Transaction] = []
    for em, data, err in results:
        if err:
            errors.append({"uid": em["uid"], "error": err})
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
        db.add(t)
        added_transactions.append(t)

    account.last_synced = datetime.utcnow()
    db.commit()

    for t in added_transactions:
        db.refresh(t)
        try:
            await rag.index_transaction(t)
        except Exception:
            pass

    added = len(added_transactions)
    return {"added": added, "skipped": len(emails) - added - len(errors), "errors": errors}


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

    try:
        await rag.index_transaction(t)
    except Exception:
        pass

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
