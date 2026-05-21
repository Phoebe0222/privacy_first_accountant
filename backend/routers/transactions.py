from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Transaction
from backend.services import rag

router = APIRouter(prefix="/transactions", tags=["transactions"])


class TransactionCreate(BaseModel):
    date: str
    vendor: str
    amount: float
    tax: float = 0.0
    category: str
    type: str
    source: str = "manual"
    description: Optional[str] = None
    invoice_number: Optional[str] = None


class TransactionUpdate(BaseModel):
    date: Optional[str] = None
    vendor: Optional[str] = None
    amount: Optional[float] = None
    tax: Optional[float] = None
    category: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    invoice_number: Optional[str] = None


@router.get("")
def list_transactions(
    type: Optional[str] = None,
    category: Optional[str] = None,
    month: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    q = db.query(Transaction)
    if type:
        q = q.filter(Transaction.type == type)
    if category:
        q = q.filter(Transaction.category == category)
    if month:
        q = q.filter(Transaction.date.like(f"{month}%"))
    total = q.count()
    items = q.order_by(Transaction.date.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [_serialize(t) for t in items]}


@router.post("")
async def create_transaction(body: TransactionCreate, db: Session = Depends(get_db)):
    t = Transaction(**body.model_dump())
    db.add(t)
    db.commit()
    db.refresh(t)
    try:
        await rag.index_transaction(t)
    except Exception:
        pass
    return _serialize(t)


@router.patch("/{transaction_id}")
async def update_transaction(
    transaction_id: int, body: TransactionUpdate, db: Session = Depends(get_db)
):
    t = db.get(Transaction, transaction_id)
    if not t:
        raise HTTPException(status_code=404, detail="Transaction not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(t, field, value)
    db.commit()
    db.refresh(t)
    try:
        await rag.index_transaction(t)
    except Exception:
        pass
    return _serialize(t)


@router.delete("/{transaction_id}")
async def delete_transaction(transaction_id: int, db: Session = Depends(get_db)):
    t = db.get(Transaction, transaction_id)
    if not t:
        raise HTTPException(status_code=404, detail="Transaction not found")
    db.delete(t)
    db.commit()
    rag.remove_transaction(transaction_id)
    return {"ok": True}


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    total_income = db.query(func.sum(Transaction.amount)).filter(Transaction.type == "income").scalar() or 0
    total_expenses = db.query(func.sum(Transaction.amount)).filter(Transaction.type == "expense").scalar() or 0

    monthly = (
        db.query(
            func.substr(Transaction.date, 1, 7).label("month"),
            Transaction.type,
            func.sum(Transaction.amount).label("total"),
        )
        .group_by("month", Transaction.type)
        .order_by("month")
        .all()
    )

    by_category = (
        db.query(Transaction.category, func.sum(Transaction.amount).label("total"))
        .filter(Transaction.type == "expense")
        .group_by(Transaction.category)
        .all()
    )

    return {
        "total_income": round(total_income, 2),
        "total_expenses": round(total_expenses, 2),
        "net_profit": round(total_income - total_expenses, 2),
        "monthly": [{"month": m, "type": tp, "total": round(tot, 2)} for m, tp, tot in monthly],
        "by_category": [{"category": c, "total": round(t, 2)} for c, t in by_category],
    }


def _serialize(t: Transaction) -> dict:
    return {
        "id": t.id,
        "date": t.date,
        "vendor": t.vendor,
        "amount": t.amount,
        "tax": t.tax,
        "category": t.category,
        "type": t.type,
        "source": t.source,
        "description": t.description,
        "invoice_number": t.invoice_number,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
