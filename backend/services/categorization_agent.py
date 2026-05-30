"""
Categorisation pipeline built with LangChain LCEL.

Chain: Rule Agent → History Agent → LLM Agent
Each step short-circuits when the category is already resolved.

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
                └──────────────────┘
"""

import logging
import os
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
    # Filled by agents as the chain progresses
    category: Optional[str] = None
    confidence: float = 0.0
    needs_review: bool = True
    method: str = "fallback"
    history_summary: str = ""


# ── Structured output schema ──────────────────────────────────────────────────

class LLMCategorizationResult(BaseModel):
    category: str = Field(description="Transaction category from the allowed list")
    confidence: float = Field(description="Confidence score 0.0 to 1.0", ge=0.0, le=1.0)
    reasoning: str = Field(description="One sentence explaining the choice")


# ── Agent 1: Deterministic rule matching ─────────────────────────────────────

def _apply_rules(state: CategorizationState) -> CategorizationState:
    if state.category is not None:
        return state
    from backend.rules.vendor_rules import INCOME_CATEGORIES
    text = f"{state.vendor} {state.description}".lower()
    for pattern, category in state.rules:
        if pattern.lower() in text:
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
    for doc in results:
        doc_vendor, doc_category = "", ""
        for line in doc.split("\n"):
            if line.startswith("Vendor:"):
                doc_vendor = line.split(":", 1)[1].strip().lower()
            elif line.startswith("Category:"):
                doc_category = line.split(":", 1)[1].strip().lower()
        if (vendor_lower and doc_vendor
                and vendor_lower not in doc_vendor
                and doc_vendor not in vendor_lower):
            continue
        if doc_category and doc_category != "other":
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
        "You are categorising financial transactions for an Australian small business. "
        "Think step by step before choosing a category, then return only the JSON object."
    )),
    ("human", (
        "Vendor: {vendor}\n"
        "Description: {description}\n"
        "Amount: ${amount}\n"
        "Type: {tx_type}\n"
        "{history_hint}\n"
        "Step 1 — What kind of business or service is this vendor?\n"
        "Step 2 — Which category below fits best?\n"
        "Step 3 — How confident are you? (0.0 = no idea, 1.0 = certain)\n\n"
        "Valid expense categories: food, grocery, cafe, transport, travel, utilities, "
        "software, marketing, fee, gym, medical, office, subscription, shopping, "
        "leisure, material, other\n"
        "Valid income categories: salary, revenue, refund"
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
            "history_hint": f"History hint: {state.history_summary}\n" if state.history_summary else "",
        })

        from backend.rules.vendor_rules import VALID_CATEGORIES
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
)


# ── Public API ────────────────────────────────────────────────────────────────

async def run_pipeline(
    vendor: str,
    description: str,
    amount: float,
    tx_type: str,
    rules: list[tuple[str, str]],
) -> dict:
    """
    Run the categorisation pipeline and return:
      category      str   — the winning category
      confidence    float — 0.0–1.0 (1.0 for rule/history hits)
      needs_review  bool  — True when confidence < CONFIDENCE_THRESHOLD
      method        str   — "rules" | "history" | "llm" | "fallback"
    """
    state = CategorizationState(
        vendor=(vendor or "").strip(),
        description=(description or "").strip(),
        amount=float(amount or 0),
        tx_type=tx_type or "expense",
        rules=rules,
    )
    final: CategorizationState = await _pipeline.ainvoke(state)
    return {
        "category": final.category or "other",
        "confidence": final.confidence,
        "needs_review": final.needs_review,
        "method": final.method,
    }
