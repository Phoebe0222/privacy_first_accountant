from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Transaction
from backend.services import rag

router = APIRouter(prefix="/rag", tags=["rag"])


@router.get("/status")
def status():
    return {"indexed_count": rag.indexed_count()}


@router.post("/reindex")
async def reindex(db: Session = Depends(get_db)):
    """Rebuild the entire vector index from the SQLite database."""
    transactions = db.query(Transaction).all()
    count = await rag.reindex_all(transactions)
    return {"indexed": count}
