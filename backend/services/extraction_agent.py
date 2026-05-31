"""
Extraction pipeline using LangChain LCEL.

  ┌─────────────────────┐
  │  Clean Text         │  Decode HTML entities, strip invisible Unicode spacers
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │  Load Rules         │  Fetch vendor rules from DB (skipped if pre-populated)
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │  RAG Search         │  Find similar past transactions for anomaly context
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │  Skip Agent         │  Is this a real completed transaction?
  └──────────┬──────────┘
             │ not skipped
             ▼
  ┌─────────────────────┐
  │  Type Agent         │  Income or expense? (regex shortcut for refunds)
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │  Fields Agent       │  Vendor, date, amount, tax, description, invoice #, anomaly
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │  Vendor Normalizer  │  Strip legal suffixes, LLM for complex names
  └──────────┬──────────┘
             ▼
  ┌─────────────────────┐
  │  Categorize         │  Rules → history consensus → LLM
  └─────────────────────┘
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
- Shipping / delivery / tracking / logistics updates: "your order has shipped", "out for delivery", "delivered", "track your package", "on its way"
- Pending or unpaid payments: "action required", "waiting for payment", "awaiting initial payment", "complete your payment", "abandoned cart", "pro forma invoice", "on its way to you", "coming soon", "will appear on your statement soon"
  EXCEPTION: a utility bill or subscription invoice with a bill period and amount due IS a real expense
- Notifications of a order completion: "order is completed", "write a review"
- Declined or failed payments: "payment declined", "card declined", "could not process", "retry payment", "billing problem", "unsuccessful", "not suscessful", "failed to charge"
- Payment status updates without confirmation of a completed charge: "your payment is being processed", "payment status update", "payment status changed"
- Rewards, gift cards, winnings: "reward points", "gift card", "you've won", "loyalty points", "cashback reward"
- Marketing or promotional offers: balance transfer offers, loan offers, "get $X eGift card"
- Account notifications without a charge: password reset, login alert, newsletter
- Statements or balance updates without a specific transaction: "your statement is ready", "your balance is $X", "account update", "your online statement is ready", "statement is now available", "your account statement", "your monthly statement", "your recent account activity"
- Payments between different accounts you hold: "payment to account", "transfer to your savings account", "transfer from your checking account"
     
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
income  = money coming IN to you: refund, salary, client payment received, payout, deposit, sale of an item

Critical rules:
- A REFUND is ALWAYS income, even if the original transaction was an expense. Look for "refund", "payout", "deposit", "sent to you", "tax refund", etc.
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

Amount rules — this is the most important field:
- Use the FINAL TOTAL the customer actually paid: look for "Total", "Amount paid", "You've paid", "Grand total", "Amount charged"
- Prefer the amount that appears last or is labelled "Total" over subtotals, item prices, or quantities
- NEVER use quantities (Qty: 200), per-unit prices ($0.35), subtotals, postage, or tax as the amount
- NEVER use ABN numbers, ACN numbers, licence numbers, account numbers, or reference numbers as the amount
- Commas are thousands separators: $1,234.56 = 1234.56 — never include commas in your output
- If no clear amount is stated, return 0.0

Date: always YYYY-MM-DD. Never use slashes or spell out the month.

invoice_number: Order #, Order ID, Invoice #, Transaction ID, Confirmation #.
Do NOT use account numbers, card numbers, ABN, or customer IDs.

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


# Invisible Unicode characters used as email spacer tricks.
# chr() keeps the source file free of invisible characters.
_INVISIBLE_CHARS = frozenset([
    chr(0x034F),  # COMBINING GRAPHEME JOINER  (&#847;)
    chr(0x00AD),  # SOFT HYPHEN
    chr(0x200B),  # ZERO WIDTH SPACE
    chr(0x200C),  # ZERO WIDTH NON-JOINER  (&zwnj;)
    chr(0x200D),  # ZERO WIDTH JOINER
    chr(0x200E),  # LEFT-TO-RIGHT MARK
    chr(0x200F),  # RIGHT-TO-LEFT MARK
    chr(0x202A),  # LEFT-TO-RIGHT EMBEDDING
    chr(0x202B),  # RIGHT-TO-LEFT EMBEDDING
    chr(0x202C),  # POP DIRECTIONAL FORMATTING
    chr(0x202D),  # LEFT-TO-RIGHT OVERRIDE
    chr(0x202E),  # RIGHT-TO-LEFT OVERRIDE
    chr(0x2060),  # WORD JOINER
    chr(0xFEFF),  # BOM / ZERO WIDTH NO-BREAK SPACE
])


def _clean_text_step(state: ExtractionState) -> ExtractionState:
    """Decode HTML entities and strip invisible Unicode characters used as email spacers."""
    import html as html_module
    text = html_module.unescape(state.text)
    text = ''.join(c for c in text if c not in _INVISIBLE_CHARS)
    text = re.sub(r"[^\S\n]+", " ", text).strip()
    return state.model_copy(update={"text": text})


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
    RunnableLambda(_clean_text_step)
    | RunnableLambda(_load_rules_step)
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

