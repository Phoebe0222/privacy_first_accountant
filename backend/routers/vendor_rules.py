from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import VendorRule
from backend.schemas import VendorRuleCreate
from backend.services.constants import VALID_CATEGORIES

router = APIRouter(prefix="/vendor-rules", tags=["vendor-rules"])


def _serialize(r: VendorRule) -> dict:
    return {"id": r.id, "vendor_pattern": r.vendor_pattern, "category": r.category, "built_in": bool(r.built_in)}


@router.get("/built-in")
def list_built_in(db: Session = Depends(get_db)):
    rules = db.query(VendorRule).filter(VendorRule.built_in == True).order_by(VendorRule.vendor_pattern).all()  # noqa: E712
    return [_serialize(r) for r in rules]


@router.get("")
def list_rules(db: Session = Depends(get_db)):
    rules = db.query(VendorRule).filter(VendorRule.built_in != True).order_by(VendorRule.vendor_pattern).all()  # noqa: E712
    return [_serialize(r) for r in rules]


@router.post("")
def create_rule(body: VendorRuleCreate, db: Session = Depends(get_db)):
    pattern = body.vendor_pattern.strip()
    if not pattern:
        raise HTTPException(status_code=400, detail="vendor_pattern must not be empty")
    if body.category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}",
        )
    rule = VendorRule(vendor_pattern=pattern, category=body.category, built_in=False)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _serialize(rule)


@router.delete("/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(VendorRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if rule.built_in:
        raise HTTPException(status_code=400, detail="Built-in rules cannot be deleted")
    db.delete(rule)
    db.commit()
    return {"ok": True}
