from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import ReconciliationMatch, Transaction
from backend.services.reconciliation_agent import get_summary, run_auto_reconcile

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


def _serialize_tx(t: Transaction) -> dict:
    return {
        "id": t.id, "date": t.date, "vendor": t.vendor,
        "amount": t.amount, "type": t.type, "category": t.category,
        "source": t.source, "description": t.description,
    }


def _serialize_match(m: ReconciliationMatch, db: Session) -> dict:
    bank = db.get(Transaction, m.bank_tx_id)
    receipt = db.get(Transaction, m.receipt_tx_id)
    return {
        "id": m.id,
        "bank": _serialize_tx(bank) if bank else None,
        "receipt": _serialize_tx(receipt) if receipt else None,
        "confidence": m.confidence,
        "status": m.status,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


# ── Summary ───────────────────────────────────────────────────────────────────

@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    return get_summary(db)


# ── Auto-reconcile ────────────────────────────────────────────────────────────

@router.post("/run")
def run(source_ref: str | None = None, db: Session = Depends(get_db)):
    return run_auto_reconcile(db, source_ref=source_ref)


# ── Matches ───────────────────────────────────────────────────────────────────

@router.get("/matches")
def list_matches(status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(ReconciliationMatch)
    if status:
        q = q.filter(ReconciliationMatch.status == status)
    matches = q.order_by(ReconciliationMatch.confidence.desc()).all()
    return [_serialize_match(m, db) for m in matches]


class MatchCreate(BaseModel):
    bank_tx_id: int
    receipt_tx_id: int


@router.post("/matches")
def create_match(body: MatchCreate, db: Session = Depends(get_db)):
    if not db.get(Transaction, body.bank_tx_id):
        raise HTTPException(status_code=404, detail="Bank transaction not found")
    if not db.get(Transaction, body.receipt_tx_id):
        raise HTTPException(status_code=404, detail="Receipt transaction not found")
    m = ReconciliationMatch(
        bank_tx_id=body.bank_tx_id,
        receipt_tx_id=body.receipt_tx_id,
        confidence=1.0,
        status="confirmed",
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _serialize_match(m, db)


@router.patch("/matches/{match_id}")
def update_match(match_id: int, status: str, db: Session = Depends(get_db)):
    m = db.get(ReconciliationMatch, match_id)
    if not m:
        raise HTTPException(status_code=404, detail="Match not found")
    if status not in ("confirmed", "rejected"):
        raise HTTPException(status_code=400, detail="status must be 'confirmed' or 'rejected'")
    m.status = status
    db.commit()
    return _serialize_match(m, db)


@router.delete("/matches/{match_id}")
def delete_match(match_id: int, db: Session = Depends(get_db)):
    m = db.get(ReconciliationMatch, match_id)
    if not m:
        raise HTTPException(status_code=404, detail="Match not found")
    db.delete(m)
    db.commit()
    return {"ok": True}


# ── Unmatched ─────────────────────────────────────────────────────────────────

@router.get("/unmatched/bank")
def unmatched_bank(db: Session = Depends(get_db)):
    matched_ids = {
        m.bank_tx_id for m in db.query(ReconciliationMatch)
        .filter(ReconciliationMatch.status != "rejected").all()
    }
    txs = db.query(Transaction).filter(
        Transaction.source == "bank_csv",
        ~Transaction.id.in_(matched_ids) if matched_ids else True,
    ).order_by(Transaction.date.desc()).all()
    return [_serialize_tx(t) for t in txs]


@router.get("/unmatched/receipts")
def unmatched_receipts(db: Session = Depends(get_db)):
    matched_ids = {
        m.receipt_tx_id for m in db.query(ReconciliationMatch)
        .filter(ReconciliationMatch.status != "rejected").all()
    }
    txs = db.query(Transaction).filter(
        Transaction.source.in_(["email", "pdf", "image"]),
        ~Transaction.id.in_(matched_ids) if matched_ids else True,
    ).order_by(Transaction.date.desc()).all()
    return [_serialize_tx(t) for t in txs]
