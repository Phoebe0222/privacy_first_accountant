from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import SessionLocal, get_db, _DEDUCTION_SEEDS
from backend.models import AppSettings, DeductionRule, Transaction

router = APIRouter(prefix="/deductions", tags=["deductions"])

_PRIMARY_SOURCES = ("bank_csv", "manual")
VALID_USER_TYPES = ("individual_salary", "individual_abn", "small_business")

_TAX_BRACKETS = [
    (18_200,       0.00, 0),
    (45_000,       0.16, 18_200),
    (135_000,      0.30, 45_000),
    (190_000,      0.37, 135_000),
    (float("inf"), 0.45, 190_000),
]


def _calc_tax(taxable_income: float) -> float:
    if taxable_income <= 0:
        return 0.0
    tax = 0.0
    for threshold, rate, base in _TAX_BRACKETS:
        if taxable_income <= threshold:
            tax += (taxable_income - base) * rate
            break
    lito = max(0.0, 700.0 - max(0.0, taxable_income - 37_500) * 0.05)
    return max(0.0, round(tax - lito + taxable_income * 0.02, 2))


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

def _calc_section(expenses: list, income: float, rules: dict) -> dict:
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

    total_deductible = round(total_deductible, 2)
    return {
        "income": round(income, 2),
        "items": items,
        "total_deductible": total_deductible,
        "total_expenses": round(sum(by_cat.values()), 2),
        "taxable_income": round(max(0.0, income - total_deductible), 2),
    }


@router.get("/estimate")
def estimate(year: int, db: Session = Depends(get_db)):
    """
    Calculate deductible amounts split by tax_kind:
      business    → transactions marked as Business
      employment  → transactions marked as Employment
    """
    date_from = f"{year}-07-01"
    date_to = f"{year + 1}-06-30"

    user_type_row = db.get(AppSettings, "user_type")
    user_type = user_type_row.value if user_type_row else "small_business"

    biz_rules = {r.category: r for r in db.query(DeductionRule).filter(DeductionRule.user_type == user_type).all()}
    emp_rules = {r.category: r for r in db.query(DeductionRule).filter(DeductionRule.user_type == "individual_salary").all()}

    def _txs(tax_kind: str, tx_type: str, category: str | None = None):
        q = (
            db.query(Transaction)
            .filter(
                Transaction.source.in_(_PRIMARY_SOURCES),
                Transaction.tax_kind == tax_kind,
                Transaction.type == tx_type,
                Transaction.date >= date_from,
                Transaction.date <= date_to,
            )
        )
        if category:
            q = q.filter(Transaction.category == category)
        return q.all()

    gross_salary_row = db.get(AppSettings, "gross_salary")
    gross_salary_setting = float(gross_salary_row.value) if gross_salary_row and gross_salary_row.value else 0.0

    payg_withheld_row = db.get(AppSettings, "payg_withheld")
    payg_withheld_setting = float(payg_withheld_row.value) if payg_withheld_row and payg_withheld_row.value else 0.0

    biz_income  = sum(t.amount or 0 for t in _txs("business",    "income", "sales"))
    tx_emp_income = sum(t.amount or 0 for t in _txs("employment", "income", "salary"))
    emp_income  = gross_salary_setting if gross_salary_setting > 0 else tx_emp_income

    business   = _calc_section(_txs("business",   "expense"), biz_income, biz_rules)
    employment = _calc_section(_txs("employment", "expense"), emp_income, emp_rules)

    biz_net    = round(biz_income - business["total_deductible"], 2)
    biz_is_loss = biz_net < 0

    if biz_is_loss:
        combined_taxable = None
        income_tax = _calc_tax(employment["taxable_income"])
    else:
        combined_taxable = max(0.0, round(employment["taxable_income"] + biz_net, 2))
        income_tax = _calc_tax(combined_taxable)

    return {
        "year": year,
        "period": f"FY{year}–{str(year + 1)[2:]}",
        "date_range": f"{date_from} to {date_to}",
        "user_type": user_type,
        "gross_salary_source": "settings" if gross_salary_setting > 0 else "transactions",
        "payg_withheld": payg_withheld_setting,
        "business": business,
        "employment": employment,
        "combined": {
            "biz_is_loss": biz_is_loss,
            "biz_net": biz_net,
            "salary_taxable": employment["taxable_income"],
            "taxable_income": combined_taxable,
            "income_tax": income_tax,
            "payg_withheld": payg_withheld_setting,
            "tax_owing": round(max(0.0, income_tax - payg_withheld_setting), 2),
            "tax_refund": round(max(0.0, payg_withheld_setting - income_tax), 2),
        },
        "total_deductible": round(business["total_deductible"] + employment["total_deductible"], 2),
        "total_expenses": round(business["total_expenses"] + employment["total_expenses"], 2),
        "items": business["items"],
    }


@router.get("/ai-estimate")
async def ai_estimate(year: int, force_refresh: bool = False, db: Session = Depends(get_db)):
    """
    AI-powered tax estimate: uses ATO rules (RAG) + LLM to assess deductibility
    of each business expense category and estimate tax payable.
    Results are cached in the DB. Pass force_refresh=true to recompute.
    `year` is the FY start year (e.g. year=2025 → FY2025-26).
    """
    import json
    from backend.models import AITaxCache
    from backend.services.tax_agent import run_tax_estimate

    if not force_refresh:
        cached = db.get(AITaxCache, year)
        if cached:
            data = json.loads(cached.result_json)
            # Invalidate cache if it's from an older format (missing biz_is_loss key)
            if isinstance(data.get("combined"), dict) and "biz_is_loss" in data["combined"] and "payg_withheld" in data["combined"]:
                return data

    result = await run_tax_estimate(year, db)

    cached = db.get(AITaxCache, year)
    if cached:
        cached.result_json = json.dumps(result)
        cached.computed_at = __import__("datetime").datetime.utcnow()
    else:
        db.add(AITaxCache(year=year, result_json=json.dumps(result)))
    db.commit()

    return result
