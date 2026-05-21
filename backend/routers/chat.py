from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import ChatMessage, Transaction
from backend.services.ai import chat as ai_chat
from backend.services import rag

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str


@router.post("")
async def send_message(body: ChatRequest, db: Session = Depends(get_db)):
    # RAG: retrieve transactions semantically relevant to the user's question
    relevant_docs = await rag.search(body.message, n_results=15) # search returns list of transaction strings most relevant to the query
    context = _build_context(db, relevant_docs) # build prompt with relevant transactions

    history = (
        db.query(ChatMessage)
        .order_by(ChatMessage.created_at.desc())
        .limit(10)
        .all()
    )
    messages = [{"role": m.role, "content": m.content} for m in reversed(history)]
    messages.append({"role": "user", "content": body.message})

    reply = await ai_chat(messages, context) # send conversation history + context to AI for response

    db.add(ChatMessage(role="user", content=body.message))
    db.add(ChatMessage(role="assistant", content=reply))
    db.commit()

    return {"reply": reply}


@router.get("/history")
def get_history(limit: int = 50, db: Session = Depends(get_db)):
    messages = (
        db.query(ChatMessage)
        .order_by(ChatMessage.created_at.asc())
        .limit(limit)
        .all()
    )
    return [{"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()} for m in messages]


@router.delete("/history")
def clear_history(db: Session = Depends(get_db)):
    db.query(ChatMessage).delete()
    db.commit()
    return {"ok": True}


def _build_context(db: Session, relevant_docs: list[str]) -> str:
    total_income = db.query(func.sum(Transaction.amount)).filter(Transaction.type == "income").scalar() or 0
    total_expenses = db.query(func.sum(Transaction.amount)).filter(Transaction.type == "expense").scalar() or 0
    net = total_income - total_expenses

    lines = [
        f"Total income: ${total_income:.2f}",
        f"Total expenses: ${total_expenses:.2f}",
        f"Net profit: ${net:.2f}",
        f"Total transactions indexed: {rag.indexed_count()}",
    ]

    # RAG results injected here
    if relevant_docs:
        lines += ["", "Most relevant transactions for this query:"]
        for doc in relevant_docs:
            lines.append(doc)  # ← each matching transaction as text
            lines.append("---")
    else:
        # Fallback when RAG index is empty
        recent = (
            db.query(Transaction)
            .order_by(Transaction.date.desc())
            .limit(20)
            .all()
        )
        lines += ["", "Recent transactions:"]
        for t in recent:
            lines.append(f"  {t.date} | {t.vendor} | {t.type} | ${t.amount:.2f} | {t.category}")

    return "\n".join(lines)
