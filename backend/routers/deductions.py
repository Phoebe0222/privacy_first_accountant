from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import SessionLocal, get_db, _DEDUCTION_SEEDS
from backend.models import AppSettings, DeductionRule, Transaction

router = APIRouter(prefix="/deductions", tags=["deductions"])

_PRIMARY_SOURCES = ("bank_csv", "manual")
VALID_USER_TYPES = ("individual_salary", "individual_abn", "small_business")


# ── Settings ──────────────────────────────────────────────────────────────────

@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    row = db.get(AppSettings, "user_type")
    return {"user_type": row.value if row else "small_business"}


class SettingsUpdate(BaseModel):
    user_type: str


@router.put("/settings")
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    if body.user_type not in VALID_USER_TYPES:
        raise HTTPException(status_code=400, detail=f"user_type must be one of {VALID_USER_TYPES}")
    row = db.get(AppSettings, "user_type")
    if row:
        row.value = body.user_type
    else:
        db.add(AppSettings(key="user_type", value=body.user_type))
    db.commit()
    return {"user_type": body.user_type}


# ── Rules CRUD ────────────────────────────────────────────────────────────────

def _serialize_rule(r: DeductionRule) -> dict:
    return {"id": r.id, "user_type": r.user_type, "category": r.category,
            "rate": r.rate, "label": r.label, "note": r.note}


@router.get("/rules")
def list_rules(user_type: str, db: Session = Depends(get_db)):
    rules = db.query(DeductionRule).filter(DeductionRule.user_type == user_type).order_by(DeductionRule.category).all()
    return [_serialize_rule(r) for r in rules]


class RuleCreate(BaseModel):
    user_type: str
    category: str
    rate: float
    label: str
    note: Optional[str] = None


@router.post("/rules")
def create_rule(body: RuleCreate, db: Session = Depends(get_db)):
    r = DeductionRule(**body.model_dump())
    db.add(r)
    db.commit()
    db.refresh(r)
    return _serialize_rule(r)


class RuleUpdate(BaseModel):
    rate: Optional[float] = None
    label: Optional[str] = None
    note: Optional[str] = None


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleUpdate, db: Session = Depends(get_db)):
    r = db.get(DeductionRule, rule_id)
    if not r:
        raise HTTPException(status_code=404, detail="Rule not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(r, field, value)
    db.commit()
    db.refresh(r)
    return _serialize_rule(r)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    r = db.get(DeductionRule, rule_id)
    if not r:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(r)
    db.commit()
    return {"ok": True}


@router.post("/rules/reset")
def reset_rules(user_type: str, db: Session = Depends(get_db)):
    """Delete all rules for this user_type and re-seed defaults."""
    if user_type not in VALID_USER_TYPES:
        raise HTTPException(status_code=400, detail="Invalid user_type")
    db.query(DeductionRule).filter(DeductionRule.user_type == user_type).delete()
    for category, rate, label, note in _DEDUCTION_SEEDS.get(user_type, []):
        db.add(DeductionRule(user_type=user_type, category=category, rate=rate, label=label, note=note))
    db.commit()
    rules = db.query(DeductionRule).filter(DeductionRule.user_type == user_type).all()
    return [_serialize_rule(r) for r in rules]


# ── Estimate ──────────────────────────────────────────────────────────────────

@router.get("/estimate")
def estimate(year: int, db: Session = Depends(get_db)):
    """
    Calculate deductible amounts for the Australian financial year starting July `year`.
    Only counts source IN ("bank_csv", "manual") + business == True.
    """
    date_from = f"{year}-07-01"
    date_to = f"{year + 1}-06-30"

    user_type_row = db.get(AppSettings, "user_type")
    user_type = user_type_row.value if user_type_row else "small_business"

    rules = {r.category: r for r in db.query(DeductionRule).filter(DeductionRule.user_type == user_type).all()}

    expenses = (
        db.query(Transaction)
        .filter(
            Transaction.source.in_(_PRIMARY_SOURCES),
            Transaction.business == True,  # noqa: E712
            Transaction.type == "expense",
            Transaction.date >= date_from,
            Transaction.date <= date_to,
        )
        .all()
    )

    # Group by category
    by_cat: dict[str, float] = {}
    for t in expenses:
        cat = t.category or "other"
        by_cat[cat] = by_cat.get(cat, 0.0) + (t.amount or 0)

    items = []
    total_deductible = 0.0
    for cat, total_spent in sorted(by_cat.items(), key=lambda x: x[1], reverse=True):
        rule = rules.get(cat) or rules.get("other")
        rate = rule.rate if rule else 0.0
        label = rule.label if rule else cat.replace("_", " ").title()
        note = rule.note if rule else None
        deductible = round(total_spent * rate, 2)
        total_deductible += deductible
        items.append({
            "category": cat,
            "label": label,
            "total_spent": round(total_spent, 2),
            "rate": rate,
            "deductible_amount": deductible,
            "note": note,
        })

    return {
        "year": year,
        "period": f"FY{year}–{str(year + 1)[2:]}",
        "date_range": f"{date_from} to {date_to}",
        "user_type": user_type,
        "items": items,
        "total_deductible": round(total_deductible, 2),
        "total_expenses": round(sum(by_cat.values()), 2),
    }
