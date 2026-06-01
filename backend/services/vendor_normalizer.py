"""
Vendor name normalisation pipeline using LangChain LCEL.

  ┌──────────────────┐
  │  Rules Step      │  Unwrap processor/bank prefix, strip noise, short-name check
  └──────────┬───────┘
             │ unresolved (> 3 words)
             ▼
  ┌──────────────────┐
  │  RAG Step        │  Find consensus name from past transactions (≥80% agreement)
  └──────────┬───────┘
             │ unresolved
             ▼
  ┌──────────────────┐
  │  LLM Step        │  Extract brand name for complex / first-seen cases
  └──────────────────┘
"""

import logging
import re
from collections import Counter
from typing import Optional

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableBranch

from backend.services.utils import get_llm

log = logging.getLogger(__name__)


# ── Pipeline state ────────────────────────────────────────────────────────────

class VendorState(BaseModel):
    raw: str
    cleaned: str = ""
    result: Optional[str] = None
    method: str = "rules"


# ── Pre-processing regexes ────────────────────────────────────────────────────

_PROCESSOR_PREFIX_RE = re.compile(
    r"^(?:paypal|stripe|sq|sp|payme|afterpay)\s*\*\s*",
    re.IGNORECASE,
)
_BANK_PREFIX_RE = re.compile(
    r"^(?:payment\s+to|direct\s+debit|direct\s+credit|eft\s+(?:to|from)|transfer\s+to)\s+",
    re.IGNORECASE,
)
_TRAILING_NOISE_RE = re.compile(
    r"\s+\d{6,}\s*$"
    r"|\s+\d[\d\s]{5,}[A-Z]{0,3}\s*$",
)
_AU_STATE_RE = re.compile(
    r"\s+\b(?:NSW|VIC|QLD|WA|SA|TAS|ACT|NT)\b\s*$",
    re.IGNORECASE,
)
_COUNTRY_CODE_RE = re.compile(
    r"\s+\b(?:HKG|HK|LUX|KOW|CHN|AUS|SGP|GBR|USA|NZL|JPN|TWN|MYS|THA|FRA|DEU|CAN|ITA|ESP)\b\s*$",
    re.IGNORECASE,
)
_PAYMENT_METHOD_RE = re.compile(
    r"\beftpos\b|\bcontactless\b|\btap\s*(&|and)\s*go\b",
    re.IGNORECASE,
)
_NA_SUFFIX_RE = re.compile(r"\s+N/?A\s*$", re.IGNORECASE)
_DOMAIN_RE = re.compile(r"\.com(\.au)?\.?|\.net(\.au)?|\.org\.?", re.IGNORECASE)
_LEGAL_RE = re.compile(
    r"\b("
    r"pty\.?\s*ltd\.?|proprietary\s+limited|private\s+limited|pte\.?\s*ltd\.?"
    r"|p/?l|plc\.?|llc\.?|inc\.?|corp\.?|ltd\.?|co\."
    r")\b",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[,\-_/\\|]+")


def _preprocess(raw: str) -> str:
    """Strip processor/bank prefixes, location noise, payment method words."""
    s = _PROCESSOR_PREFIX_RE.sub("", raw)
    s = _BANK_PREFIX_RE.sub("", s)
    s = _TRAILING_NOISE_RE.sub("", s)
    s = _AU_STATE_RE.sub("", s)
    s = _COUNTRY_CODE_RE.sub("", s)
    s = _NA_SUFFIX_RE.sub("", s)
    s = _PAYMENT_METHOD_RE.sub("", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def _rule_clean(raw: str) -> str:
    """Strip legal suffixes, domains, and punctuation."""
    s = _DOMAIN_RE.sub("", raw)
    s = _LEGAL_RE.sub("", s)
    s = _PUNCT_RE.sub(" ", s)
    return re.sub(r"\s{2,}", " ", s).strip(" .,")


def _fix_case(s: str) -> str:
    return s.title() if s == s.upper() else s


# ── Step 1: Rules ─────────────────────────────────────────────────────────────

def _rules_step(state: VendorState) -> VendorState:
    cleaned = _rule_clean(_preprocess(state.raw)) or _preprocess(state.raw)
    updates: dict = {"cleaned": cleaned}
    if len(cleaned.split()) <= 3:
        updates["result"] = _fix_case(cleaned)
        updates["method"] = "rules"
    return state.model_copy(update=updates)


# ── Step 2: RAG ───────────────────────────────────────────────────────────────

async def _rag_step(state: VendorState) -> VendorState:
    if state.result is not None:
        return state
    try:
        from backend.services import rag
        results = await rag.search(f"vendor:{state.cleaned}", n_results=10)
    except Exception:
        return state

    vendor_lower = state.cleaned.lower()
    names: list[str] = []
    for doc in results:
        doc_vendor = ""
        for line in doc.split("\n"):
            if line.startswith("Vendor:"):
                doc_vendor = line.split(":", 1)[1].strip()
                break
        if not doc_vendor:
            continue
        # Normalize the candidate so stale DB entries don't propagate wrong names
        doc_vendor = _fix_case(_rule_clean(_preprocess(doc_vendor)))
        dv_lower = doc_vendor.lower()
        if vendor_lower in dv_lower or dv_lower in vendor_lower:
            names.append(doc_vendor)

    if not names:
        return state

    most_common, count = Counter(names).most_common(1)[0]
    if count / len(names) >= 0.8:
        log.debug("Vendor via RAG | %r → %r (%d/%d)", state.raw, most_common, count, len(names))
        return state.model_copy(update={"result": most_common, "method": "history"})
    return state


# ── Step 3: LLM ───────────────────────────────────────────────────────────────

class _NormResult(BaseModel):
    name: str = Field(description="The clean, recognizable brand or business name")


_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Extract the recognizable brand or business name from a raw bank statement description.\n\n"
     "Rules:\n"
     "1. Remove bank card purchase prefixes — the real merchant follows the card number:\n"
     "   'VISA DEBIT PURCHASE CARD 5001 HUNGRYPANDA' → 'HungryPanda'\n"
     "   'EFTPOS PURCHASE CARD 2971 GONG CHA' → 'Gong Cha'\n"
     "   'MASTERCARD PURCHASE 1234 URBAN CLIMB' → 'Urban Climb'\n"
     "2. Remove PayPal/Stripe/Square prefixes:\n"
     "   'PAYPAL *AIAUMARKETS 0401100630 AUS' → 'AIAUMARKETS'\n"
     "   'STRIPE *EXAMPLE 1234567890 AUS' → 'EXAMPLE'\n"
     "   'SQUARE *EXAMPLE 1234567890 AUS' → 'EXAMPLE'\n"
     "3. Remove street addresses, suburbs, cities, states, and country codes appended after the brand.\n"
     "   'GONG CHA SPENCER ST MELBOURNE' → 'Gong Cha'\n"
     "   'ALICE AND OLIVIA HK RE TSIM SHA TSUI' → 'Alice and Olivia'\n"
     "   'Chow Sang Sang Kowloon' → 'Chow Sang Sang'\n"
     "   EXCEPTION: keep geography when it IS the brand: 'Australia Post', 'Air New Zealand'.\n"
     "3. Remove legal suffixes: Pty Ltd, Private Limited, Pte Ltd, Inc, LLC, Corp, Ltd.\n"
     "4. Split compact domain-style names: 'laprairie' → 'La Prairie', "
     "'world.taobao' → 'Taobao', 'pc.meitu' → 'Meitu'.\n"
     "5. Remove 'HK RE ...' address sequences.\n"
     "6. Remove platform descriptors: E-commerce, Holdings, Group, International.\n"
     "7. Title-case all-uppercase names.\n"
     "Return ONLY the JSON object."),
    ("human", "Vendor: {vendor}"),
])


async def _llm_step(state: VendorState) -> VendorState:
    if state.result is not None:
        return state
    try:
        chain = _PROMPT | get_llm().with_structured_output(_NormResult)
        norm: _NormResult = await chain.ainvoke({"vendor": state.raw})
        result = norm.name.strip() or _fix_case(state.cleaned)
        log.debug("Vendor via LLM | %r → %r", state.raw, result)
        return state.model_copy(update={"result": result, "method": "llm"})
    except Exception as exc:
        log.debug("Vendor LLM failed for %r: %s", state.raw, exc)
        return state.model_copy(update={"result": _fix_case(state.cleaned), "method": "rules"})


# ── LCEL pipeline ─────────────────────────────────────────────────────────────

def _resolved(state: VendorState) -> bool:
    return state.result is not None


_pipeline = (
    RunnableLambda(_rules_step)
    | RunnableBranch(
        (_resolved, RunnableLambda(lambda s: s)),
        RunnableLambda(_rag_step),
    )
    | RunnableBranch(
        (_resolved, RunnableLambda(lambda s: s)),
        RunnableLambda(_llm_step),
    )
)


# ── Cache + public API ────────────────────────────────────────────────────────

_cache: dict[str, str] = {}


async def normalize_vendor(raw: str) -> str:
    """Return a normalized vendor name. Falls back to the input on any error."""
    if not raw or raw in ("Unknown", ""):
        return raw
    if raw in _cache:
        return _cache[raw]
    final: VendorState = await _pipeline.ainvoke(VendorState(raw=raw))
    result = final.result or _fix_case(_rule_clean(_preprocess(raw))) or raw
    _cache[raw] = result
    return result
