"""
Extraction pipeline using LangChain LCEL.
Replaces the single monolithic EXTRACTION_PROMPT with three focused agents:

  ┌──────────────┐
  │  Skip Agent  │  Is this a real completed transaction?
  └──────┬───────┘
         │ not skipped
         ▼
  ┌──────────────┐
  │  Type Agent  │  Income or expense?
  └──────┬───────┘
         ↓
  ┌──────────────┐
  │ Fields Agent │  Extract vendor, date, amount, tax, description, invoice #, anomaly
  └──────────────┘
"""

import logging
import os
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableBranch
from backend.services.utils import get_llm

log = logging.getLogger(__name__)

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
EXTRACT_MODEL = os.getenv("EXTRACT_MODEL", "llama3.2:3b")
VISION_MODEL = os.getenv("VISION_MODEL", "moondream2")


# ── Pipeline state ────────────────────────────────────────────────────────────

class ExtractionState(BaseModel):
    text: str
    similar_docs: list[str] = []
    rules: list[tuple[str, str]] = []
    # Filled progressively by each agent
    skip: bool = False
    skip_reason: Optional[str] = None
    tx_type: Optional[str] = None
    vendor: Optional[str] = None
    date: Optional[str] = None
    amount: Optional[float] = None
    tax: float = 0.0
    description: Optional[str] = None
    invoice_number: Optional[str] = None
    anomaly: bool = False
    anomaly_reason: Optional[str] = None
    category: str = "other"
    category_confidence: float = 0.0
    needs_review: bool = True

    model_config = {"arbitrary_types_allowed": True}


# ── Structured output schemas ─────────────────────────────────────────────────

class SkipDecision(BaseModel):
    skip: bool = Field(description="True if this is NOT a completed financial transaction")
    reason: Optional[str] = Field(default=None, description="Brief reason if skip=True, else null")


class TypeDecision(BaseModel):
    type: Literal["income", "expense"] = Field(
        description="'expense' = money going out from you, 'income' = money coming in to you"
    )


class FieldsExtraction(BaseModel):
    vendor: str = Field(description="Company or person name")
    date: Optional[str] = Field(default=None, description="Date in YYYY-MM-DD format")
    amount: float = Field(description="Transaction amount as plain decimal, e.g. 1000.00 not 1,000")
    tax: float = Field(default=0.0, description="GST or tax amount; 0.0 if not stated")
    description: str = Field(description="One-line summary of the transaction")
    invoice_number: Optional[str] = Field(
        default=None,
        description="Order #, Invoice #, Transaction ID. NOT an account number or card number.",
    )
    anomaly: bool = Field(default=False, description="True if amount differs significantly from past transactions")
    anomaly_reason: Optional[str] = Field(default=None, description="Brief explanation if anomaly=True")


# ── Agent 1: Skip detection ───────────────────────────────────────────────────

_SKIP_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """\
You are a financial email filter. Decide if this email describes a COMPLETED transaction where money actually changed hands.

Set skip=true for ANY of these (no money moved):
- Shipping / delivery / tracking / logistics updates
- Pending or unpaid payments: "waiting for payment", "complete your payment", "abandoned cart", "pro forma invoice"
  EXCEPTION: a utility bill or subscription invoice with a bill period and amount due IS a real expense
- Declined or failed payments: "payment declined", "card declined", "could not process", "retry payment", "billing problem"
- Rewards, gift cards, winnings: "reward points", "gift card", "you've won", "loyalty points", "cashback reward"
- Marketing or promotional offers: balance transfer offers, loan offers, "get $X eGift card"
- Account notifications without a charge: password reset, login alert, newsletter

Set skip=false for:
- Payment receipts and order / booking confirmations
- Utility bills and subscription invoices (even if payment is future-dated)
- Refund confirmations
- Bank payment or deposit confirmations

Return ONLY the JSON object."""),
    ("human", "Email:\n{text}"),
])


async def _skip_agent(state: ExtractionState) -> ExtractionState:
    try:
        chain = _SKIP_PROMPT | get_llm().with_structured_output(SkipDecision)
        result: SkipDecision = await chain.ainvoke({"text": state.text[:3000]})
        log.debug("Skip agent: skip=%s reason=%s", result.skip, result.reason)
        return state.model_copy(update={"skip": result.skip, "skip_reason": result.reason})
    except Exception as e:
        log.warning("Skip agent failed: %s — defaulting to not skip", e)
        return state


# ── Agent 2: Income / expense classification ──────────────────────────────────

# Patterns that unambiguously indicate money coming IN — bypass the LLM for these
_INCOME_RE = re.compile(
    r"\brefund(ed|ing)?\b"
    r"|\bpartial\s+refund\b"
    r"|\bwe.?ve\s+(issued|processed|sent)\s+(a\s+)?refund\b"
    r"|\byour\s+refund\b"
    r"|\bpayout\s+(of|has\s+been)\b"
    r"|\bfunds?\s+(have\s+been\s+)?(sent|transferred|deposited)\s+to\s+you\b"
    r"|\byou\s+have\s+been\s+paid\b",
    re.IGNORECASE,
)

_TYPE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """\
Classify a financial transaction as income or expense.

expense = money going OUT from you: bill, invoice, receipt, subscription charge, order confirmation
income  = money coming IN to you: refund, salary, client payment received, payout, deposit

Critical rules:
- A REFUND is ALWAYS income
- "payment received" or "we received your payment" means the MERCHANT received money FROM YOU — EXPENSE
- "Receipt for your payment" or "Thank you for your payment" = EXPENSE
- A positive dollar amount does NOT mean income — invoices and receipts always show positive amounts
- Default to "expense" when uncertain

Return ONLY the JSON object."""),
    ("human", "Transaction:\n{text}"),
])


async def _type_agent(state: ExtractionState) -> ExtractionState:
    if state.skip:
        return state
    if _INCOME_RE.search(state.text[:500]):
        log.debug("Type agent: income (regex shortcut)")
        return state.model_copy(update={"tx_type": "income"})
    try:
        chain = _TYPE_PROMPT | get_llm().with_structured_output(TypeDecision)
        result: TypeDecision = await chain.ainvoke({"text": state.text[:2000]})
        log.debug("Type agent: type=%s", result.type)
        return state.model_copy(update={"tx_type": result.type})
    except Exception as e:
        log.warning("Type agent failed: %s — defaulting to expense", e)
        return state.model_copy(update={"tx_type": "expense"})


# ── Agent 3: Field extraction ─────────────────────────────────────────────────

_FIELDS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """\
Extract transaction fields from a financial document.
Transaction type is already known: {tx_type}

Number format (Australian documents):
- Commas are THOUSANDS SEPARATORS: $1,000 = 1000.00   $1,234.56 = 1234.56
- Never write commas in your output amounts

Date format: always YYYY-MM-DD (e.g. 2024-03-15). Never use slashes or spell out the month.

For invoice_number: look for Order #, Invoice #, Ref, Transaction ID, Confirmation #.
Do NOT use account numbers, card numbers, or customer IDs.

{similar_hint}
Return ONLY the JSON object."""),
    ("human", "Document:\n{text}"),
])


async def _fields_agent(state: ExtractionState) -> ExtractionState:
    if state.skip:
        return state
    similar_hint = ""
    if state.similar_docs: # if we have similar past transactions from RAG, show the top 3 as examples to guide the extraction and anomaly detection
        preview = "\n---\n".join(state.similar_docs[:3])
        similar_hint = (
            f"Past similar transactions (for anomaly detection):\n{preview}\n\n"
            "If the current amount is more than 2x the typical past amount for this vendor, "
            "set anomaly=true and briefly explain in anomaly_reason."
        )
    try:
        from backend.services.utils import normalise_date
        chain = _FIELDS_PROMPT | get_llm().with_structured_output(FieldsExtraction)
        result: FieldsExtraction = await chain.ainvoke({
            "text": state.text[:3000],
            "tx_type": state.tx_type or "expense",
            "similar_hint": similar_hint,
        })
        return state.model_copy(update={
            "vendor": result.vendor,
            "date": normalise_date(result.date) if result.date else None,
            "amount": result.amount,
            "tax": result.tax,
            "description": result.description,
            "invoice_number": result.invoice_number,
            "anomaly": result.anomaly,
            "anomaly_reason": result.anomaly_reason,
        })
    except Exception as e:
        log.warning("Fields agent failed: %s — marking as skip", e)
        return state.model_copy(update={"skip": True, "skip_reason": f"extraction failed: {e}"})


async def _load_rules_step(state: ExtractionState) -> ExtractionState:
    if state.rules:
        return state
    from backend.database import SessionLocal
    from backend.models import VendorRule
    from backend.services.vendor_rules import BUILT_IN_RULES
    db = SessionLocal()
    try:
        user_rules = db.query(VendorRule).all()
        user_pairs = sorted(
            [(r.vendor_pattern.lower().strip(), r.category) for r in user_rules],
            key=lambda x: len(x[0]),
            reverse=True,
        )
        return state.model_copy(update={"rules": user_pairs + BUILT_IN_RULES})
    finally:
        db.close()


async def _rag_search_step(state: ExtractionState) -> ExtractionState:
    if state.similar_docs:
        return state
    try:
        from backend.services import rag
        similar = await rag.search(state.text[:300], n_results=5)
        return state.model_copy(update={"similar_docs": similar})
    except Exception:
        return state


async def _vendor_normalizer(state: ExtractionState) -> ExtractionState:
    if state.skip or not state.vendor:
        return state
    from backend.services.vendor_normalizer import normalize_vendor
    return state.model_copy(update={"vendor": await normalize_vendor(state.vendor)})


async def _categorize_step(state: ExtractionState) -> ExtractionState:
    if state.skip or not state.rules:
        return state
    from backend.services.categorization_agent import categorize_transaction
    cat = await categorize_transaction(
        vendor=state.vendor or "",
        description=state.description or "",
        amount=float(state.amount or 0),
        tx_type=state.tx_type or "expense",
        rules=state.rules,
    )
    return state.model_copy(update={
        "category": cat["category"],
        "category_confidence": cat["confidence"],
        "needs_review": cat["needs_review"],
    })


# ── LCEL pipeline ─────────────────────────────────────────────────────────────

_pipeline = (
    RunnableLambda(_load_rules_step)
    | RunnableLambda(_rag_search_step)
    | RunnableLambda(_skip_agent)
    | RunnableBranch(
        (lambda s: s.skip, RunnableLambda(lambda s: s)),
        RunnableLambda(_type_agent) | RunnableLambda(_fields_agent),
    )
    | RunnableLambda(_vendor_normalizer)
    | RunnableLambda(_categorize_step)
)


# ── Public API ────────────────────────────────────────────────────────────────

async def extract_from_text(text: str) -> dict:
    state = ExtractionState(text=text)
    final: ExtractionState = await _pipeline.ainvoke(state)
    return {
        "skip": final.skip,
        "date": final.date,
        "vendor": final.vendor,
        "amount": final.amount,
        "tax": final.tax,
        "type": final.tx_type or "expense",
        "description": final.description,
        "invoice_number": final.invoice_number,
        "anomaly": final.anomaly,
        "anomaly_reason": final.anomaly_reason,
        "category": final.category,
        "category_confidence": final.category_confidence,
        "needs_review": final.needs_review,
    }


async def extract_from_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """OCR an image with the vision model. Returns raw text, or empty string on failure."""
    import base64
    import httpx

    b64 = base64.b64encode(image_bytes).decode()
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{OLLAMA_BASE}/api/generate",
                json={
                    "model": VISION_MODEL,
                    "prompt": (
                        "Describe all text visible in this receipt or invoice image. "
                        "Include vendor name, date, amounts, tax, and any invoice number."
                    ),
                    "images": [b64],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            return resp.json()["response"]
    except Exception as e:
        log.warning("Vision OCR failed: %s", e)
        return ""

