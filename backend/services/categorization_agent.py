"""
Categorisation pipeline built with LangChain LCEL.

Chain: Rule Agent → History Agent → LLM Agent → Tax Kind Agent
The first three steps short-circuit when the category is already resolved.
The Tax Kind Agent always runs, regardless of how the category was resolved.

                ┌──────────────────┐
  state ──────► │  apply_rules     │ (pure Python, no LLM)
                └────────┬─────────┘
                         │ unresolved
                         ▼
                ┌──────────────────┐
                │  search_history  │ (RAG consensus)
                └────────┬─────────┘
                         │ unresolved
                         ▼
                ┌──────────────────┐
                │  llm_categorize  │ (ChatOllama + structured output)
                └────────┬─────────┘
                         │ always
                         ▼
                ┌──────────────────┐
                │ classify_tax_kind│ (static map, else ATO-RAG + ChatOllama)
                └──────────────────┘
"""

import logging
import os
import re
from collections import Counter
from typing import Optional

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableBranch
from backend.services.utils import get_llm

log = logging.getLogger(__name__)

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
EXTRACT_MODEL = os.getenv("EXTRACT_MODEL", "llama3.2:3b")
CONFIDENCE_THRESHOLD = 0.7
HISTORY_THRESHOLD = 0.8


# ── Pipeline state ────────────────────────────────────────────────────────────

class CategorizationState(BaseModel):
    vendor: str
    description: str
    amount: float
    tx_type: str
    rules: list[tuple[str, str]]
    bank_category: str = ""
    # Filled by agents as the chain progresses
    category: Optional[str] = None
    confidence: float = 0.0
    needs_review: bool = True
    method: str = "fallback"
    history_summary: str = ""
    tax_kind: str = "na"


# ── Structured output schema ──────────────────────────────────────────────────

class LLMCategorizationResult(BaseModel):
    category: str = Field(description="Transaction category from the allowed list")
    confidence: float = Field(description="Confidence score 0.0 to 1.0", ge=0.0, le=1.0)
    reasoning: str = Field(description="One sentence explaining the choice")


# ── Agent 1: Deterministic rule matching ─────────────────────────────────────

_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _apply_rules(state: CategorizationState) -> CategorizationState:
    if state.category is not None:
        return state
    from backend.services.constants import INCOME_CATEGORIES
    text = _NORMALIZE_RE.sub(" ", f"{state.vendor} {state.description}".lower())
    for pattern, category in state.rules:
        pattern_norm = _NORMALIZE_RE.sub(" ", pattern.lower())
        if pattern_norm and pattern_norm in text:
            if state.tx_type == "income" and category not in INCOME_CATEGORIES:
                continue
            if state.tx_type == "expense" and category in INCOME_CATEGORIES:
                continue
            log.debug("Rule match: '%s' → %s", pattern, category)
            return state.model_copy(update={
                "category": category,
                "confidence": 1.0,
                "needs_review": False,
                "method": "rules",
            })
    return state


# ── Agent 2: History consensus via RAG ───────────────────────────────────────

async def _search_history(state: CategorizationState) -> CategorizationState:
    if state.category is not None:
        return state
    try:
        from backend.services.rag import search
        results = await search( # search for similar past transactions to find consensus category for this vendor/description
            f"vendor:{state.vendor} {state.description[:100]}", n_results=10
        )
    except Exception:
        return state

    categories: list[str] = []
    vendor_lower = state.vendor.lower()
    desc_lower = (state.description or "").lower()
    for doc in results:
        doc_vendor, doc_category, doc_desc = "", "", ""
        for line in doc.split("\n"):
            if line.startswith("Vendor:"):
                doc_vendor = line.split(":", 1)[1].strip().lower()
            elif line.startswith("Category:"):
                doc_category = line.split(":", 1)[1].strip().lower()
            elif line.startswith("Description:"):
                doc_desc = line.split(":", 1)[1].strip().lower()

        vendor_match = bool(
            vendor_lower and doc_vendor
            and (vendor_lower in doc_vendor or doc_vendor in vendor_lower)
        )
        desc_match = bool(
            desc_lower and doc_desc
            and len(desc_lower) > 5
            and (desc_lower[:30] in doc_desc or doc_desc[:30] in desc_lower)
        )
        if not vendor_match and not desc_match:
            continue
        from backend.services.constants import VALID_CATEGORIES
        if doc_category and doc_category != "other" and doc_category in VALID_CATEGORIES:
            categories.append(doc_category)

    if not categories:
        return state

    counts = Counter(categories)
    most_common, count = counts.most_common(1)[0]
    confidence = count / len(categories)
    summary = f"Past {len(categories)} transactions: '{most_common}' in {count}/{len(categories)}"

    if confidence >= HISTORY_THRESHOLD:
        log.debug("History consensus: %s → %s (%.0f%%)", state.vendor, most_common, confidence * 100)
        return state.model_copy(update={
            "category": most_common,
            "confidence": confidence,
            "needs_review": False,
            "method": "history",
        })
    return state.model_copy(update={"history_summary": summary})


# ── Agent 3: LLM categorisation (ChatOllama + structured output) ──────────────

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", (
        "You are categorising financial transactions from an Australian bank account that contains "
        "a mix of personal and business purchases. "
        "Think step by step before choosing a category, then return only the JSON object."
    )),
    ("human", (
        "Vendor: {vendor}\n"
        "Description: {description}\n"
        "Amount: ${amount}\n"
        "Type: {tx_type}\n"
        "{bank_category_hint}"
        "{history_hint}\n"
        "Step 1 — Read the description carefully. If the vendor is generic (e.g. PayPal, bank), "
        "use the description to identify the real merchant or purpose.\n"
        "Step 2 — Which category fits best?\n"
        "Step 3 — How confident are you in the category? (0.0–1.0)\n\n"
        "Amount hint: if the amount is under $15 and the vendor is a coffee shop, "
        "bubble tea, or café — use 'drink', not 'food'. "
        "Use 'drink' for coffee, tea, bubble tea, smoothies. "
        "Use 'food' for meals, restaurants, takeaway.\n\n"
        "Valid expense categories: food, grocery, drink, transport, travel, utilities, "
        "software, marketing, fee, gym, medical, office, home_office, subscription, shopping, "
        "leisure, material, other\n"
        "Valid income categories: sales (product/service sales with GST), revenue (dividends, rent, other non-GST income), salary, refund"
    )),
])

async def _llm_categorize(state: CategorizationState) -> CategorizationState:
    if state.category is not None:
        return state
    try:
        chain = _PROMPT | get_llm().with_structured_output(LLMCategorizationResult)
        result: LLMCategorizationResult = await chain.ainvoke({
            "vendor": state.vendor,
            "description": state.description[:300],
            "amount": f"{float(state.amount or 0):.2f}",
            "tx_type": state.tx_type or "expense",
            "bank_category_hint": f"Bank category (hint only, may not match valid list): {state.bank_category}\n" if state.bank_category else "",
            "history_hint": f"History hint: {state.history_summary}\n" if state.history_summary else "",
        })

        from backend.services.constants import VALID_CATEGORIES
        category = result.category if result.category in VALID_CATEGORIES else "other"
        confidence = max(0.0, min(1.0, result.confidence))
        if category == "other" and result.category != "other":
            confidence = max(confidence - 0.2, 0.0)

        needs_review = confidence < CONFIDENCE_THRESHOLD
        log.info(
            "LLM categorize | %s → %s (%.0f%%) needs_review=%s | %s",
            state.vendor, category, confidence * 100, needs_review, result.reasoning,
        )
        return state.model_copy(update={
            "category": category,
            "confidence": confidence,
            "needs_review": needs_review,
            "method": "llm",
        })
    except Exception as e:
        log.warning("LLM categorize failed for '%s': %s", state.vendor, e)
        return state  # leaves category=None, method="fallback"


# ── Agent 4: Tax-kind classification (ATO-RAG + ChatOllama) ───────────────────

TAX_YEAR = "2025-2026"

# Categories whose tax_kind is unambiguous regardless of vendor — skip RAG/LLM.
_STATIC_TAX_KIND: dict[str, str] = {
    "salary": "employment",
    "refund": "na",
    "sales": "business",
    "marketing": "business",
    "material": "business",
    "grocery": "na",
    "drink": "na",
    "food": "na",
    "gym": "na",
    "leisure": "na",
    "shopping": "na",
    "medical": "na",
}


class TaxKindResult(BaseModel):
    tax_kind: str = Field(
        description=(
            "Tax treatment of this transaction — must be one of:\n"
            "'business' — business expense or business income (sole trader/ABN activity).\n"
            "'employment' — work-related deduction for a PAYG salary earner.\n"
            "'na' — personal, non-deductible, or not applicable."
        )
    )
    reasoning: str = Field(description="One sentence explaining the choice, citing the ATO guidance if relevant")


_TAX_KIND_PROMPT = ChatPromptTemplate.from_messages([
    ("system", (
        "You are an Australian tax assistant. The taxpayer has both PAYG salary income and a "
        "sole trader/small business ABN. Decide how this transaction should be treated for tax "
        f"purposes in the {TAX_YEAR} financial year, using the ATO guidance excerpts as context. "
        "Think step by step, then return only the JSON object."
    )),
    ("human", (
        "Vendor: {vendor}\n"
        "Description: {description}\n"
        "Category: {category}\n"
        "Amount: ${amount}\n"
        "Type: {tx_type}\n\n"
        "ATO guidance ({tax_year}):\n{ato_context}\n\n"
        "Step 1 — Could this plausibly be a business expense/income (sole trader activity)?\n"
        "Step 2 — If not, is it a work-related expense a PAYG salary earner could claim as a "
        "deduction (per the ATO guidance above)?\n"
        "Step 3 — Otherwise classify as 'na' (personal/non-deductible).\n"
    )),
])


async def _classify_tax_kind(state: CategorizationState) -> CategorizationState:
    category = state.category or "other"
    static = _STATIC_TAX_KIND.get(category)
    if static is not None:
        return state.model_copy(update={"tax_kind": static})

    ato_context = "(no relevant ATO guidance found)"
    try:
        from backend.services.rag import search_ato_rules
        query = f"{category} {state.vendor} {state.description[:100]}".strip()
        hits = await search_ato_rules(query, year=TAX_YEAR, n_results=3)
        if hits:
            ato_context = "\n---\n".join(h["text"] for h in hits)
    except Exception as e:
        log.warning("ATO rule lookup failed for '%s': %s", state.vendor, e)

    try:
        chain = _TAX_KIND_PROMPT | get_llm().with_structured_output(TaxKindResult)
        result: TaxKindResult = await chain.ainvoke({
            "vendor": state.vendor,
            "description": state.description[:300],
            "category": category,
            "amount": f"{float(state.amount or 0):.2f}",
            "tx_type": state.tx_type or "expense",
            "tax_year": TAX_YEAR,
            "ato_context": ato_context,
        })
        tax_kind = result.tax_kind if result.tax_kind in ("business", "employment", "na") else "na"
        log.info("Tax kind classify | %s (%s) → %s | %s", state.vendor, category, tax_kind, result.reasoning)
        return state.model_copy(update={"tax_kind": tax_kind})
    except Exception as e:
        log.warning("Tax kind classification failed for '%s': %s", state.vendor, e)
        return state


# ── LCEL pipeline ─────────────────────────────────────────────────────────────

def _resolved(state: CategorizationState) -> bool:
    return state.category is not None


_pipeline = (
    RunnableLambda(_apply_rules)
    | RunnableBranch(
        (_resolved, RunnableLambda(lambda s: s)),
        RunnableLambda(_search_history),
    )
    | RunnableBranch(
        (_resolved, RunnableLambda(lambda s: s)),
        RunnableLambda(_llm_categorize),
    )
    | RunnableLambda(_classify_tax_kind)
)


# ── Public API ────────────────────────────────────────────────────────────────

async def categorize_transaction(
    vendor: str,
    description: str,
    amount: float,
    tx_type: str,
    rules: list[tuple[str, str]],
    bank_category: str = "",
) -> dict:
    """
    Run the categorisation pipeline and return:
      category      str   — the winning category
      confidence    float — 0.0–1.0 (1.0 for rule/history hits)
      needs_review  bool  — True when confidence < CONFIDENCE_THRESHOLD
      method        str   — "rules" | "history" | "llm" | "fallback"
      tax_kind      str   — "business" | "employment" | "na"
    """
    state = CategorizationState(
        vendor=(vendor or "").strip(),
        description=(description or "").strip(),
        amount=float(amount or 0),
        tx_type=tx_type or "expense",
        rules=rules,
        bank_category=(bank_category or "").strip(),
    )
    final: CategorizationState = await _pipeline.ainvoke(state)
    return {
        "category": final.category or "other",
        "confidence": final.confidence,
        "needs_review": final.needs_review,
        "method": final.method,
        "tax_kind": final.tax_kind,
        "business": final.tax_kind == "business",
    }
