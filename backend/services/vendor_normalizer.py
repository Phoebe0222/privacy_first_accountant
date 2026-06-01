"""
Vendor name normalisation.

Step 1 — payment processor unwrapping: "PAYPAL *AIAUMARKETS 4029357733 AUS" → "AIAUMARKETS"
Step 2 — deterministic rules: strip legal suffixes and domain parts.
Step 3 — RAG history: if past transactions agree on a canonical name, use it.
Step 4 — LLM fallback: only when RAG has no match and the name is still complex.

Results are cached in-process so each raw name is resolved at most once.

Examples
--------
"PAYPAL *AIAUMARKETS 4029357733 AUS"              → "Aiau Markets"
"STRIPE *SOME COMPANY"                            → "Some Company"
"alibaba"                                         → "Alibaba"
"AIAU MARKETS PTY LTD"                            → "AIAU Markets"
"Alibaba.com Singapore E-commerce Pte Ltd"        → "Alibaba"  (via RAG or LLM)
"PayPal Australia Pty Limited"                    → "PayPal"
"""

import logging
import re
from collections import Counter
from typing import Optional

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from backend.services.utils import get_llm

log = logging.getLogger(__name__)

# ── Payment processor unwrapping ─────────────────────────────────────────────
# "PAYPAL *MERCHANT 4029357733 AUS" → "MERCHANT"
# "STRIPE *SOME CO" → "SOME CO"

_PROCESSOR_PREFIX_RE = re.compile(
    r"^(?:paypal|stripe|sq|sp|payme|afterpay)\s*\*\s*",
    re.IGNORECASE,
)
_TRAILING_PHONE_RE = re.compile(
    r"\s+\d[\d\s]{5,}[A-Z]{0,3}\s*$",  # phone number + optional country code
)


def _unwrap_processor(raw: str) -> str:
    """Strip payment processor prefix and trailing phone/country noise."""
    unwrapped = _PROCESSOR_PREFIX_RE.sub("", raw)
    if unwrapped == raw:
        return raw
    return _TRAILING_PHONE_RE.sub("", unwrapped).strip()


# ── Rule-based cleanup ────────────────────────────────────────────────────────

_DOMAIN_RE = re.compile(r"\.com(\.au)?\.?|\.net(\.au)?|\.org\.?", re.IGNORECASE)

_LEGAL_RE = re.compile(
    r"\b("
    r"pty\.?\s*ltd\.?|proprietary\s+limited|private\s+limited|pte\.?\s*ltd\.?"
    r"|p/?l|plc\.?|llc\.?|inc\.?|corp\.?|ltd\.?|co\."
    r")\b",
    re.IGNORECASE,
)

_PUNCT_RE = re.compile(r"[,\-_/\\|]+")


def _rule_clean(raw: str) -> str:
    s = _DOMAIN_RE.sub("", raw)
    s = _LEGAL_RE.sub("", s)
    s = _PUNCT_RE.sub(" ", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" .,")
    return s


def _fix_case(s: str) -> str:
    """Title-case only when the whole string is uppercase; otherwise preserve."""
    return s.title() if s == s.upper() else s


# ── RAG history lookup ────────────────────────────────────────────────────────

async def _rag_vendor(raw: str, cleaned: str) -> Optional[str]:
    """
    Search past transactions for a vendor similar to `raw`.
    Returns the most-used canonical name if ≥80% of matches agree, else None.
    """
    try:
        from backend.services import rag
        results = await rag.search(f"vendor:{cleaned}", n_results=10)
    except Exception:
        return None

    vendor_lower = cleaned.lower()
    names: list[str] = []
    for doc in results:
        doc_vendor = ""
        for line in doc.split("\n"):
            if line.startswith("Vendor:"):
                doc_vendor = line.split(":", 1)[1].strip()
                break
        if not doc_vendor:
            continue
        # Only count docs that are about a similar vendor
        dv_lower = doc_vendor.lower()
        if vendor_lower in dv_lower or dv_lower in vendor_lower:
            names.append(doc_vendor)

    if not names:
        return None

    most_common, count = Counter(names).most_common(1)[0]
    if count / len(names) >= 0.8:
        log.debug("Vendor normalized via RAG | %r → %r (%d/%d)", raw, most_common, count, len(names))
        return most_common
    return None


# ── LLM structured output ─────────────────────────────────────────────────────

class _NormResult(BaseModel):
    name: str = Field(description="The clean, recognizable brand or business name")


_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "Extract the core brand or business name from a raw vendor string. "
     "Remove: legal entity suffixes (Pty Ltd, Private Limited, Pte Ltd, Inc, LLC, Corp, etc.), "
     "platform descriptors (E-commerce, Holdings, Group, International). "
     "Normalize capitalization (title case for all-uppercase names). "
     "Return ONLY the JSON object."),
    ("human", "Vendor: {vendor}"),
])

# ── In-process cache ──────────────────────────────────────────────────────────

_cache: dict[str, str] = {}


# ── Public API ────────────────────────────────────────────────────────────────

async def normalize_vendor(raw: str) -> str:
    """Return a normalized vendor name. Falls back to the input on any error."""
    if not raw or raw in ("Unknown", ""):
        return raw

    if raw in _cache:
        return _cache[raw]

    # Step 1: unwrap payment processor prefix ("PAYPAL *MERCHANT ..." → "MERCHANT")
    unwrapped = _unwrap_processor(raw)
    cleaned = _rule_clean(unwrapped)
    if not cleaned:
        cleaned = raw

    # Step 1: rules alone are sufficient for short names
    if len(cleaned.split()) <= 3:
        result = _fix_case(cleaned)
        _cache[raw] = result
        return result

    # Step 2: RAG — reuse the canonical name from past transactions
    rag_result = await _rag_vendor(raw, cleaned)
    if rag_result:
        _cache[raw] = rag_result
        return rag_result

    # Step 3: LLM for complex names with no history
    try:
        chain = _PROMPT | get_llm().with_structured_output(_NormResult)
        norm: _NormResult = await chain.ainvoke({"vendor": raw})
        result = norm.name.strip() or _fix_case(cleaned)
        log.debug("Vendor normalized via LLM | %r → %r", raw, result)
    except Exception as exc:
        log.debug("Vendor normalization LLM failed for %r: %s", raw, exc)
        result = _fix_case(cleaned)

    _cache[raw] = result
    return result
