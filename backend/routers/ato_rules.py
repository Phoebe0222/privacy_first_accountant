from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import ATORule
from backend.schemas import ATORuleCreate

router = APIRouter(prefix="/ato-rules", tags=["ato-rules"])


def _serialize(r: ATORule) -> dict:
    return {"id": r.id, "title": r.title, "description": r.description}


@router.get("")
def list_rules(db: Session = Depends(get_db)):
    return [_serialize(r) for r in db.query(ATORule).order_by(ATORule.title).all()]


@router.post("")
def create_rule(body: ATORuleCreate, db: Session = Depends(get_db)):
    title = body.title.strip()
    description = body.description.strip()
    if not title or not description:
        raise HTTPException(status_code=400, detail="title and description must not be empty")
    rule = ATORule(title=title, description=description)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _serialize(rule)


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(ATORule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"ok": True}
