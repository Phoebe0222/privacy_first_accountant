"""
AI tax agent: goes through transactions and estimates tax deductibles and tax
payable, split by income source:

  Salary section   → salary income  +  work-related deductions (personal expenses)
  Business section → sales income   +  business expense deductions
  Combined         → total taxable income → estimated tax payable

Australian tax brackets: Stage 3, effective FY2024-25 onward.
"""
import logging
import os
from typing import Optional

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from backend.services.utils import get_llm

log = logging.getLogger(__name__)

CHAT_MODEL = os.getenv("CHAT_MODEL", "qwen2.5:7b")

# ── Australian tax brackets (Stage 3, effective FY2024-25 onward) ─────────────

_BRACKETS = [
    (18_200,       0.00, 0),
    (45_000,       0.16, 18_200),
    (135_000,      0.30, 45_000),
    (190_000,      0.37, 135_000),
    (float("inf"), 0.45, 190_000),
]
_LOW_INCOME_OFFSET_MAX = 700
# TODO: medicare levy surcharge only applies for high-income earners without private health insurance
# add an option in the tax settings and adjust the calculation accordingly
_MEDICARE = 0.02


def _calc_tax(taxable_income: float) -> float:
    if taxable_income <= 0:
        return 0.0
    tax = 0.0
    for threshold, rate, base in _BRACKETS:
        if taxable_income <= threshold:
            tax += (taxable_income - base) * rate
            break
    lito = max(0, _LOW_INCOME_OFFSET_MAX - max(0, taxable_income - 37_500) * 0.05)
    medicare = max(0, taxable_income * _MEDICARE)
    return max(0, round(tax - lito + medicare, 2))


# ── Deductibility assessment via LLM + ATO RAG ────────────────────────────────

class _Assessment(BaseModel):
    rate: float = Field(description="Fraction deductible 0.0–1.0.")
    reasoning: str = Field(description="One sentence explaining deductibility under Australian tax law.")
    ato_reference: str = Field(description="ATO rule or section referenced.")


_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You are an Australian tax adviser. Given an expense category, sample vendors, "
     "total spent, taxpayer type, and relevant ATO guidance, assess what fraction is "
     "tax deductible.\n\n"
     "Rate 1.0 = fully deductible, 0.5 = partially deductible, 0.0 = not deductible.\n"
     "Taxpayer type context:\n"
     "  - 'salary': PAYG employee — only work-related expenses are deductible\n"
     "  - 'business': sole trader / small business — business expenses are deductible\n"
     "Use the ATO context provided. If unsure, be conservative.\n"
     "Return ONLY the JSON object."),
    ("human",
     "Taxpayer type: {taxpayer_type}\n"
     "Category: {category}\n"
     "Sample vendors: {vendors}\n"
     "Total spent: ${total:.2f}\n\n"
     "ATO guidance:\n{ato_context}"),
])


async def _assess(
    category: str,
    vendors: list[str],
    total: float,
    ato_context: str,
    taxpayer_type: str,
) -> _Assessment:
    chain = _PROMPT | get_llm(model=CHAT_MODEL).with_structured_output(_Assessment)
    return await chain.ainvoke({
        "taxpayer_type": taxpayer_type,
        "category": category,
        "vendors": ", ".join(vendors[:8]),
        "total": total,
        "ato_context": ato_context or "No specific ATO guidance found.",
    })


async def _assess_category_group(
    by_cat: dict,
    taxpayer_type: str,
    ato_year: str,
    rag,
    amount_fn=None,
) -> tuple[list[dict], float]:
    """Assess all categories in a group. Returns (items, total_deductible)."""
    _amt = amount_fn or (lambda t: t.amount or 0)
    items = []
    total_deductible = 0.0

    for cat, cat_txs in sorted(by_cat.items(), key=lambda x: sum(_amt(t) for t in x[1]), reverse=True):
        total_spent = round(sum(_amt(t) for t in cat_txs), 2)
        vendors = list({t.vendor for t in cat_txs if t.vendor and t.vendor != "Unknown"})

        query = (
            f"Is {cat.replace('_', ' ')} deductible for Australian "
            f"{'employee' if taxpayer_type == 'salary' else 'small business'}?"
        )
        ato_results = await rag.search_ato_rules(query, year=ato_year, n_results=3)
        ato_context = "\n\n".join(r["text"] for r in ato_results)
        ato_urls    = list({r["url"] for r in ato_results if r["url"]})

        try:
            assessment = await _assess(cat, vendors, total_spent, ato_context, taxpayer_type)
            rate      = max(0.0, min(1.0, assessment.rate))
            reasoning = assessment.reasoning
            reference = assessment.ato_reference
        except Exception as e:
            log.warning("Tax agent failed for %s/%s: %s", taxpayer_type, cat, e)
            rate, reasoning, reference = 0.5, "Could not assess — defaulting to 50%.", ""

        deductible = round(total_spent * rate, 2)
        total_deductible += deductible

        items.append({
            "category":          cat,
            "total_spent":       total_spent,
            "deductible_rate":   rate,
            "deductible_amount": deductible,
            "reasoning":         reasoning,
            "ato_reference":     reference,
            "ato_urls":          ato_urls,
            "transaction_count": len(cat_txs),
        })

    return items, round(total_deductible, 2)


# ── Public API ────────────────────────────────────────────────────────────────

async def run_tax_estimate(year: int, db) -> dict:
    """
    Split tax estimate:
      - Salary: salary income + work-related deductions (personal/non-business expenses)
      - Business: sales income + business expense deductions
      - Combined: total taxable income → estimated tax payable
    """
    from backend.models import Transaction, AppSettings
    from backend.services import rag

    date_from = f"{year}-07-01"
    date_to   = f"{year + 1}-06-30"
    tax_year  = f"{year}-{str(year + 1)[2:]}"
    ato_year  = "2025-2026"

    # Tax profile settings
    gst_row = db.get(AppSettings, "gst_registered")
    gst_registered = (gst_row.value == "true") if gst_row else False

    gross_salary_row = db.get(AppSettings, "gross_salary")
    gross_salary_setting = float(gross_salary_row.value) if gross_salary_row and gross_salary_row.value else 0.0

    payg_withheld_row = db.get(AppSettings, "payg_withheld")
    payg_withheld_setting = float(payg_withheld_row.value) if payg_withheld_row and payg_withheld_row.value else 0.0

    def _tax_excl(t) -> float:
        """Return GST-exclusive amount for business transactions when GST registered."""
        if gst_registered:
            return max(0.0, (t.amount or 0) - (t.tax or 0))
        return t.amount or 0

    base = dict(
        source_filter=["bank_csv", "manual"],
        date_from=date_from,
        date_to=date_to,
    )

    def _query(extra_filters):
        return (
            db.query(Transaction)
            .filter(
                Transaction.source.in_(base["source_filter"]),
                Transaction.date >= base["date_from"],
                Transaction.date <= base["date_to"],
                *extra_filters,
            )
            .all()
        )

    # ── Salary section ────────────────────────────────────────────────────────
    # Income: prefer settings-based YTD gross salary; fall back to transactions
    salary_income_txs = _query([Transaction.type == "income", Transaction.category == "salary"])
    tx_salary_income = round(sum(t.amount for t in salary_income_txs), 2)
    salary_income = gross_salary_setting if gross_salary_setting > 0 else tx_salary_income

    # Deductions: expenses the categorisation agent flagged as work-related
    employment_expense_txs = _query([
        Transaction.type == "expense",
        Transaction.tax_kind == "employment",
    ])
    salary_by_cat: dict[str, list] = {}
    for t in employment_expense_txs:
        salary_by_cat.setdefault(t.category or "other", []).append(t)

    salary_items, salary_deductible = await _assess_category_group(
        salary_by_cat, "salary", ato_year, rag
    )
    salary_taxable = max(0.0, round(salary_income - salary_deductible, 2))

    # ── Business section ──────────────────────────────────────────────────────
    # Income: sales transactions marked as business
    biz_income_txs = _query([
        Transaction.type == "income",
        Transaction.category == "sales",
        Transaction.tax_kind == "business",
    ])
    biz_income = round(sum(_tax_excl(t) for t in biz_income_txs), 2)

    # Deductions: business expenses
    biz_expense_txs = _query([
        Transaction.type == "expense",
        Transaction.tax_kind == "business",
    ])
    biz_by_cat: dict[str, list] = {}
    for t in biz_expense_txs:
        biz_by_cat.setdefault(t.category or "other", []).append(t)

    biz_items, biz_deductible = await _assess_category_group(
        biz_by_cat, "business", ato_year, rag, amount_fn=_tax_excl
    )
    biz_taxable = max(0.0, round(biz_income - biz_deductible, 2))

    # ── Combined — non-commercial loss rules (Div 35 ITAA 1997) ─────────────
    biz_net = round(biz_income - biz_deductible, 2)
    biz_is_loss = biz_net < 0

    if biz_is_loss:
        # Business is in loss — cannot automatically offset salary.
        # Scenario A: NCL rules apply → only salary taxable, loss deferred.
        # Scenario B: NCL test passed or ATI > $250k → loss offsets salary.
        taxable_ncl_applies  = salary_taxable                            # loss deferred
        taxable_ncl_exempt   = max(0.0, round(salary_taxable + biz_net, 2))  # loss offsets

        ncl_applies_tax = _calc_tax(taxable_ncl_applies)
        ncl_exempt_tax  = _calc_tax(taxable_ncl_exempt)
        combined = {
            "salary_taxable":        salary_taxable,
            "biz_net":               biz_net,
            "biz_is_loss":           True,
            "payg_withheld":         payg_withheld_setting,
            "ncl_applies": {
                "taxable_income":    taxable_ncl_applies,
                "estimated_tax":     ncl_applies_tax,
                "tax_owing":         round(max(0.0, ncl_applies_tax - payg_withheld_setting), 2),
                "tax_refund":        round(max(0.0, payg_withheld_setting - ncl_applies_tax), 2),
                "note":              "Business loss deferred — applies unless you meet the income requirement (taxable income, reportable fringe benefits, reportable super contributions and net investment losses, excluding this business loss, under $250,000) and pass one of the four non-commercial loss tests.",
            },
            "ncl_exempt": {
                "taxable_income":    taxable_ncl_exempt,
                "estimated_tax":     ncl_exempt_tax,
                "tax_owing":         round(max(0.0, ncl_exempt_tax - payg_withheld_setting), 2),
                "tax_refund":        round(max(0.0, payg_withheld_setting - ncl_exempt_tax), 2),
                "note":              "If your income (excluding this business loss) is under $250,000 and you pass one of the four NCL tests (income ≥ $20k, 3-of-5 profit years, real property ≥ $500k, other assets ≥ $100k), the loss can offset your salary.",
            },
            "ncl_tests_url":         "https://www.ato.gov.au/businesses-and-organisations/income-deductions-and-concessions/losses/non-commercial-losses/what-is-a-non-commercial-loss",
            "tax_brackets":          "Stage 3 (FY2024-25+): 0/16/30/37/45% + 2% Medicare",
        }
    else:
        # Business is profitable — combine normally.
        combined_taxable = round(salary_taxable + biz_taxable, 2)
        estimated_tax    = _calc_tax(combined_taxable)
        combined = {
            "salary_taxable":        salary_taxable,
            "biz_net":               biz_net,
            "biz_is_loss":           False,
            "taxable_income":        combined_taxable,
            "estimated_tax":         estimated_tax,
            "payg_withheld":         payg_withheld_setting,
            "tax_owing":             round(max(0.0, estimated_tax - payg_withheld_setting), 2),
            "tax_refund":            round(max(0.0, payg_withheld_setting - estimated_tax), 2),
            "tax_brackets":          "Stage 3 (FY2024-25+): 0/16/30/37/45% + 2% Medicare",
        }

    return {
        "tax_year": f"FY{tax_year}",
        "period":   f"{date_from} to {date_to}",
        "salary": {
            "income":            salary_income,
            "total_expenses":    round(sum(t.amount for t in employment_expense_txs), 2),
            "total_deductible":  salary_deductible,
            "taxable_income":    salary_taxable,
            "items":             salary_items,
        },
        "business": {
            "income":            biz_income,
            "gst_registered":    gst_registered,
            "total_expenses":    round(sum(_tax_excl(t) for t in biz_expense_txs), 2),
            "total_deductible":  biz_deductible,
            "taxable_income":    biz_taxable,
            "items":             biz_items,
        },
        "combined":  combined,
        "note": (
            "Estimate only. Does not account for offsets, depreciation, prior losses, "
            "or personal circumstances. Non-commercial loss rules (Div 35 ITAA 1997) apply "
            "when business makes a loss. Consult a registered tax agent."
        ),
    }
