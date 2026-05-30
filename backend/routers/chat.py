from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import ATORule, ChatMessage
from backend.schemas import ChatRequest
from backend.services.chat_agent import chat as ai_chat

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("")
async def send_message(body: ChatRequest, db: Session = Depends(get_db)):
    history = (
        db.query(ChatMessage)
        .order_by(ChatMessage.created_at.desc())
        .limit(10)
        .all()
    )
    messages = [{"role": m.role, "content": m.content} for m in reversed(history)]
    messages.append({"role": "user", "content": body.message})

    ato_rules = db.query(ATORule).order_by(ATORule.title).all()
    system_context = ""
    if ato_rules:
        system_context = "Australian tax rules:\n" + "\n".join(
            f"- {r.title}: {r.description}" for r in ato_rules
        )

    reply = await ai_chat(messages, system_context)

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
