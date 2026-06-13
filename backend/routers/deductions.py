from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import SessionLocal, get_db, _DEDUCTION_SEEDS
from backend.models import AppSettings, DeductionRule, Transaction
from backend.services.tax_calculate import calc_tax

router = APIRouter(prefix="/deductions", tags=["deductions"])

_PRIMARY_SOURCES = ("bank_csv", "manual")
VALID_USER_TYPES = ("individual_salary", "individual_abn", "small_business")


# ── Settings ──────────────────────────────────────────────────────────────────

def _get_carryforward(db: Session) -> float:
    row = db.get(AppSettings, "business_loss_carryforward")
    return float(row.value) if row and row.value else 0.0


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    row = db.get(AppSettings, "user_type")
    return {
        "user_type": row.value if row else "small_business",
        "business_loss_carryforward": _get_carryforward(db),
    }


class SettingsUpdate(BaseModel):
    user_type: str
    business_loss_carryforward: Optional[float] = None


@router.put("/settings")
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    if body.user_type not in VALID_USER_TYPES:
        raise HTTPException(status_code=400, detail=f"user_type must be one of {VALID_USER_TYPES}")
    row = db.get(AppSettings, "user_type")
    if row:
        row.value = body.user_type
    else:
        db.add(AppSettings(key="user_type", value=body.user_type))

    if body.business_loss_carryforward is not None:
        cf_value = max(0.0, body.business_loss_carryforward)
        cf_row = db.get(AppSettings, "business_loss_carryforward")
        if cf_row:
            cf_row.value = str(cf_value)
        else:
            db.add(AppSettings(key="business_loss_carryforward", value=str(cf_value)))

    db.commit()
    return {"user_type": body.user_type, "business_loss_carryforward": _get_carryforward(db)}


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

    phi_row = db.get(AppSettings, "private_hospital_cover")
    has_private_hospital_cover = (phi_row.value == "true") if phi_row else False

    biz_income  = sum(t.amount or 0 for t in _txs("business",    "income", "sales"))
    tx_emp_income = sum(t.amount or 0 for t in _txs("employment", "income", "salary"))
    emp_income  = gross_salary_setting if gross_salary_setting > 0 else tx_emp_income

    business   = _calc_section(_txs("business",   "expense"), biz_income, biz_rules)
    employment = _calc_section(_txs("employment", "expense"), emp_income, emp_rules)

    biz_net    = round(biz_income - business["total_deductible"], 2)
    biz_is_loss = biz_net < 0

    carryforward_balance = _get_carryforward(db)
    combined_extra: dict = {"carryforward_balance": round(carryforward_balance, 2)}

    if biz_is_loss:
        # A business loss can't automatically offset salary income (Div 35 ITAA 1997 —
        # non-commercial loss rules). Show both possible outcomes:
        #  - ncl_applies: loss is deferred and added to the carryforward balance
        #  - ncl_exempt:  an NCL test is passed, so the loss offsets salary this year
        taxable_ncl_applies = employment["taxable_income"]
        taxable_ncl_exempt  = max(0.0, round(employment["taxable_income"] + biz_net, 2))
        tax_ncl_applies = calc_tax(taxable_ncl_applies, has_private_hospital_cover)
        tax_ncl_exempt  = calc_tax(taxable_ncl_exempt, has_private_hospital_cover)

        combined_taxable = None
        income_tax = tax_ncl_applies

        combined_extra.update({
            "ncl_applies": {
                "taxable_income":     taxable_ncl_applies,
                "income_tax":         tax_ncl_applies,
                "tax_owing":          round(max(0.0, tax_ncl_applies - payg_withheld_setting), 2),
                "tax_refund":         round(max(0.0, payg_withheld_setting - tax_ncl_applies), 2),
                "carryforward_after": round(carryforward_balance + abs(biz_net), 2),
                "note": "Business loss deferred — added to your loss carryforward balance to offset future business profits. Applies unless you meet the income requirement (taxable income, reportable fringe benefits, reportable super contributions and net investment losses, excluding this business loss, under $250,000) and pass one of the four non-commercial loss tests.",
            },
            "ncl_exempt": {
                "taxable_income":     taxable_ncl_exempt,
                "income_tax":         tax_ncl_exempt,
                "tax_owing":          round(max(0.0, tax_ncl_exempt - payg_withheld_setting), 2),
                "tax_refund":         round(max(0.0, payg_withheld_setting - tax_ncl_exempt), 2),
                "carryforward_after": round(carryforward_balance, 2),
                "note": "If your income (excluding this business loss) is under $250,000 and you pass one of the four NCL tests (assessable income ≥ $20k, 3-of-5 profit years, real property ≥ $500k, other assets ≥ $100k), this year's loss offsets your salary immediately instead of being carried forward.",
            },
            "ncl_tests_url": "https://www.ato.gov.au/businesses-and-organisations/income-deductions-and-concessions/losses/non-commercial-losses/what-is-a-non-commercial-loss",
        })
    else:
        # Apply any losses carried forward from previous years against this year's
        # business profit before combining with salary.
        carryforward_used      = round(min(biz_net, carryforward_balance), 2)
        biz_net_after_cf       = round(biz_net - carryforward_used, 2)
        carryforward_remaining = round(carryforward_balance - carryforward_used, 2)

        combined_taxable = max(0.0, round(employment["taxable_income"] + biz_net_after_cf, 2))
        income_tax = calc_tax(combined_taxable, has_private_hospital_cover)

        combined_extra.update({
            "carryforward_used":          carryforward_used,
            "carryforward_remaining":     carryforward_remaining,
            "biz_net_after_carryforward": biz_net_after_cf,
        })

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
            **combined_extra,
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
