from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import get_db, _DEFAULT_DEDUCTION_RULES, SessionLocal
from backend.models import AppSettings, DeductionRule, Transaction
from backend.schemas import DeductionRuleCreate, DeductionRuleUpdate

router = APIRouter(prefix="/deductions", tags=["deductions"])

_VALID_USER_TYPES = {"individual_salary", "individual_abn", "small_business"}
_PRIMARY_SOURCES = ("bank_csv", "manual")


def _serialize_rule(r: DeductionRule) -> dict:
    return {
        "id": r.id,
        "user_type": r.user_type,
        "category": r.category,
        "rate": r.rate,
        "label": r.label,
        "note": r.note,
    }


# ── Settings ────────────────────────────────────────────────────────────────

@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    setting = db.get(AppSettings, "user_type")
    return {"user_type": setting.value if setting else "small_business"}


@router.put("/settings")
def update_settings(body: dict, db: Session = Depends(get_db)):
    user_type = body.get("user_type")
    if user_type not in _VALID_USER_TYPES:
        raise HTTPException(status_code=400, detail=f"user_type must be one of: {', '.join(_VALID_USER_TYPES)}")
    setting = db.get(AppSettings, "user_type")
    if setting:
        setting.value = user_type
    else:
        db.add(AppSettings(key="user_type", value=user_type))
    db.commit()
    return {"user_type": user_type}


# ── Rules CRUD ───────────────────────────────────────────────────────────────

@router.get("/rules")
def list_rules(user_type: str, db: Session = Depends(get_db)):
    if user_type not in _VALID_USER_TYPES:
        raise HTTPException(status_code=400, detail=f"user_type must be one of: {', '.join(_VALID_USER_TYPES)}")
    rules = db.query(DeductionRule).filter(DeductionRule.user_type == user_type).all()
    return [_serialize_rule(r) for r in rules]


@router.post("/rules")
def create_rule(body: DeductionRuleCreate, db: Session = Depends(get_db)):
    if body.user_type not in _VALID_USER_TYPES:
        raise HTTPException(status_code=400, detail=f"user_type must be one of: {', '.join(_VALID_USER_TYPES)}")
    if not 0.0 <= body.rate <= 1.0:
        raise HTTPException(status_code=400, detail="rate must be between 0.0 and 1.0")
    rule = DeductionRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _serialize_rule(rule)


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: int, body: DeductionRuleUpdate, db: Session = Depends(get_db)):
    rule = db.get(DeductionRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if body.rate is not None and not 0.0 <= body.rate <= 1.0:
        raise HTTPException(status_code=400, detail="rate must be between 0.0 and 1.0")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return _serialize_rule(rule)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(DeductionRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"ok": True}


@router.post("/rules/reset")
def reset_rules(user_type: str, db: Session = Depends(get_db)):
    """Delete all rules for this user_type and re-seed from defaults."""
    if user_type not in _VALID_USER_TYPES:
        raise HTTPException(status_code=400, detail=f"user_type must be one of: {', '.join(_VALID_USER_TYPES)}")
    db.query(DeductionRule).filter(DeductionRule.user_type == user_type).delete()
    for category, rate, label, note in _DEFAULT_DEDUCTION_RULES.get(user_type, []):
        db.add(DeductionRule(user_type=user_type, category=category, rate=rate, label=label, note=note))
    db.commit()
    rules = db.query(DeductionRule).filter(DeductionRule.user_type == user_type).all()
    return [_serialize_rule(r) for r in rules]


# ── Estimate ─────────────────────────────────────────────────────────────────

@router.get("/estimate")
def get_estimate(year: int, db: Session = Depends(get_db)):
    setting = db.get(AppSettings, "user_type")
    user_type = setting.value if setting else "small_business"

    rules = db.query(DeductionRule).filter(DeductionRule.user_type == user_type).all()
    rule_map = {r.category: r for r in rules}

    date_start = f"{year}-01-01"
    date_end = f"{year}-12-31"

    rows = (
        db.query(Transaction.category, func.sum(Transaction.amount).label("total"))
        .filter(
            Transaction.type == "expense",
            Transaction.source.in_(_PRIMARY_SOURCES),
            Transaction.business == True,  # noqa: E712
            Transaction.date >= date_start,
            Transaction.date <= date_end,
        )
        .group_by(Transaction.category)
        .all()
    )

    items = []
    total_deductible = 0.0
    for category, total_spent in rows:
        rule = rule_map.get(category)
        if not rule:
            continue
        deductible = round(total_spent * rule.rate, 2)
        total_deductible += deductible
        items.append({
            "category": category,
            "label": rule.label,
            "total_spent": round(total_spent, 2),
            "rate": rule.rate,
            "deductible_amount": deductible,
            "note": rule.note,
        })

    items.sort(key=lambda x: x["deductible_amount"], reverse=True)

    return {
        "year": year,
        "user_type": user_type,
        "items": items,
        "total_deductible": round(total_deductible, 2),
    }
