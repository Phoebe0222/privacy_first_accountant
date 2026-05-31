from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, asc, desc
from sqlalchemy.orm import Session

from fastapi.responses import Response
from backend.database import get_db
from backend.models import Attachment, Transaction
from backend.schemas import TransactionCreate, TransactionUpdate
from backend.services import rag

router = APIRouter(prefix="/transactions", tags=["transactions"])


SORTABLE_COLUMNS = {"date", "vendor", "category", "type", "source", "amount", "tax"}

@router.get("")
def list_transactions(
    type: Optional[str] = None,
    category: Optional[str] = None,
    month: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    source: Optional[str] = None,
    vendor: Optional[str] = None,
    needs_review: Optional[bool] = None,
    anomaly: Optional[bool] = None,
    sort_by: str = "date",
    sort_dir: str = "desc",
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
    if date_from:
        q = q.filter(Transaction.date >= date_from)
    if date_to:
        q = q.filter(Transaction.date <= date_to)
    if source:
        q = q.filter(Transaction.source == source)
    if vendor:
        q = q.filter(Transaction.vendor.ilike(f"%{vendor}%"))
    if needs_review is not None:
        q = q.filter(Transaction.needs_review == needs_review)
    if anomaly is not None:
        q = q.filter(Transaction.anomaly == anomaly)
    total = q.count()
    col = getattr(Transaction, sort_by if sort_by in SORTABLE_COLUMNS else "date")
    order = desc(col) if sort_dir == "desc" else asc(col)
    items = q.order_by(order).offset(offset).limit(limit).all()
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
    # User correcting a category means they're confident — clear the review flag
    if body.category is not None:
        t.needs_review = False
        t.category_confidence = 1.0
    db.commit()
    db.refresh(t)
    try:
        await rag.index_transaction(t)
    except Exception:
        pass
    return _serialize(t)


@router.get("/review-queue")
def review_queue(db: Session = Depends(get_db)):
    """Return transactions flagged for category review, lowest confidence first."""
    items = (
        db.query(Transaction)
        .filter(Transaction.needs_review == True)  # noqa: E712
        .order_by(Transaction.category_confidence.asc())
        .limit(100)
        .all()
    )
    return {"count": len(items), "items": [_serialize(t) for t in items]}


@router.delete("")
async def bulk_delete(source_ref: Optional[str] = None, source: Optional[str] = None, db: Session = Depends(get_db)):
    if not source_ref and not source:
        raise HTTPException(status_code=400, detail="Provide source_ref or source")
    q = db.query(Transaction.id)
    if source_ref:
        q = q.filter(Transaction.source_ref == source_ref)
    if source:
        q = q.filter(Transaction.source == source)
    ids = [row.id for row in q.all()]
    if not ids:
        raise HTTPException(status_code=404, detail="No transactions found")
    db.query(Transaction).filter(Transaction.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    # Batch-delete from ChromaDB in a thread so we don't block the event loop
    import asyncio
    str_ids = [str(i) for i in ids]
    await asyncio.get_event_loop().run_in_executor(None, lambda: rag._col.delete(ids=str_ids))
    return {"deleted": len(ids)}


@router.get("/{transaction_id}/attachments")
def list_attachments(transaction_id: int, db: Session = Depends(get_db)):
    atts = db.query(Attachment).filter(Attachment.transaction_id == transaction_id).all()
    return [{"id": a.id, "filename": a.filename, "mime_type": a.mime_type} for a in atts]


@router.get("/{transaction_id}/attachments/{attachment_id}")
def get_attachment(transaction_id: int, attachment_id: int, db: Session = Depends(get_db)):
    a = db.query(Attachment).filter(
        Attachment.id == attachment_id,
        Attachment.transaction_id == transaction_id,
    ).first()
    if not a:
        raise HTTPException(status_code=404, detail="Attachment not found")
    filename = a.filename or f"attachment_{a.id}"
    return Response(
        content=a.data,
        media_type=a.mime_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.delete("/{transaction_id}")
async def delete_transaction(transaction_id: int, db: Session = Depends(get_db)):
    t = db.get(Transaction, transaction_id)
    if not t:
        raise HTTPException(status_code=404, detail="Transaction not found")
    db.delete(t)
    db.commit()
    rag.remove_transaction(transaction_id)
    return {"ok": True}


@router.get("/imports")
def list_imports(db: Session = Depends(get_db)):
    rows = (
        db.query(
            Transaction.source,
            Transaction.source_ref,
            func.count(Transaction.id).label("count"),
            func.min(Transaction.date).label("date_from"),
            func.max(Transaction.date).label("date_to"),
            func.max(Transaction.created_at).label("imported_at"),
        )
        .filter(Transaction.source.in_(["csv", "pdf", "image"]))
        .filter(Transaction.source_ref.isnot(None))
        .group_by(Transaction.source, Transaction.source_ref)
        .order_by(func.max(Transaction.created_at).desc())
        .all()
    )
    return [
        {
            "source": r.source,
            "source_ref": r.source_ref,
            "count": r.count,
            "date_from": r.date_from,
            "date_to": r.date_to,
            "imported_at": r.imported_at.isoformat() if r.imported_at else None,
        }
        for r in rows
    ]


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
        "anomaly": t.anomaly or False,
        "anomaly_reason": t.anomaly_reason,
        "needs_review": t.needs_review or False,
        "category_confidence": t.category_confidence,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
