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
) -> tuple[list[dict], float]:
    """Assess all categories in a group. Returns (items, total_deductible)."""
    items = []
    total_deductible = 0.0

    for cat, cat_txs in sorted(by_cat.items(), key=lambda x: sum(t.amount for t in x[1]), reverse=True):
        total_spent = round(sum(t.amount for t in cat_txs), 2)
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
    from backend.models import Transaction
    from backend.services import rag

    date_from = f"{year}-07-01"
    date_to   = f"{year + 1}-06-30"
    tax_year  = f"{year}-{str(year + 1)[2:]}"
    ato_year  = "2025-2026"

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
    # Income: salary transactions (PAYG — any business flag)
    salary_income_txs = _query([Transaction.type == "income", Transaction.category == "salary"])
    salary_income = round(sum(t.amount for t in salary_income_txs), 2)

    # Deductions: personal/unclassified expenses that may be work-related for PAYG earners
    personal_expense_txs = _query([
        Transaction.type == "expense",
        Transaction.tax_kind.in_(["employment", "na"]),
    ])
    salary_by_cat: dict[str, list] = {}
    for t in personal_expense_txs:
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
    biz_income = round(sum(t.amount for t in biz_income_txs), 2)

    # Deductions: business expenses
    biz_expense_txs = _query([
        Transaction.type == "expense",
        Transaction.tax_kind == "business",
    ])
    biz_by_cat: dict[str, list] = {}
    for t in biz_expense_txs:
        biz_by_cat.setdefault(t.category or "other", []).append(t)

    biz_items, biz_deductible = await _assess_category_group(
        biz_by_cat, "business", ato_year, rag
    )
    biz_taxable = max(0.0, round(biz_income - biz_deductible, 2))

    # ── Combined ──────────────────────────────────────────────────────────────
    combined_taxable = round(salary_taxable + biz_taxable, 2)
    estimated_tax    = _calc_tax(combined_taxable)

    return {
        "tax_year": f"FY{tax_year}",
        "period":   f"{date_from} to {date_to}",
        "salary": {
            "income":            salary_income,
            "total_expenses":    round(sum(t.amount for t in personal_expense_txs), 2),
            "total_deductible":  salary_deductible,
            "taxable_income":    salary_taxable,
            "items":             salary_items,
        },
        "business": {
            "income":            biz_income,
            "total_expenses":    round(sum(t.amount for t in biz_expense_txs), 2),
            "total_deductible":  biz_deductible,
            "taxable_income":    biz_taxable,
            "items":             biz_items,
        },
        "combined": {
            "total_income":      round(salary_income + biz_income, 2),
            "total_deductible":  round(salary_deductible + biz_deductible, 2),
            "taxable_income":    combined_taxable,
            "estimated_tax":     estimated_tax,
            "tax_brackets":      "Stage 3 (FY2024-25+): 0/16/30/37/45% + 2% Medicare",
        },
        "note": (
            "Estimate only. Does not account for offsets, levies, prior losses, "
            "depreciation, or personal circumstances. Consult a registered tax agent."
        ),
    }
