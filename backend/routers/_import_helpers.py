"""
Shared state and helpers used by all three import routers.
"""
import asyncio
import logging
import re

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import Transaction, VendorRule
from backend.services import rag
from backend.services.constants import INCOME_CATEGORIES

log = logging.getLogger(__name__)

# ── Shared job store ──────────────────────────────────────────────────────────

_jobs: dict[str, dict] = {}

router = APIRouter(prefix="/import", tags=["import"])


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── Shared helpers ────────────────────────────────────────────────────────────

def _load_category_rules(db) -> list[tuple[str, str]]:
    """Return all vendor rules sorted longest-first (built-in and user-defined are all in DB)."""
    all_rules = db.query(VendorRule).all()
    return sorted(
        [(r.vendor_pattern.lower().strip(), r.category) for r in all_rules],
        key=lambda x: len(x[0]),
        reverse=True,
    )


def _is_content_duplicate(db: Session, data: dict) -> bool:
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
        needs_review=bool(data.get("needs_review", False)),
        category_confidence=data.get("category_confidence"),
        business=bool(data.get("business", False)),
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
