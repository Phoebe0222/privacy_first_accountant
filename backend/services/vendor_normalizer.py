"""
Vendor name normalisation.

Step 1 — deterministic rules: strip legal suffixes, domain parts, geographic words.
Step 2 — LLM (only when the cleaned name is still complex, i.e. > 3 words).

Results are cached in-process so the LLM is called at most once per unique raw name.

Examples
--------
"alibaba"                                         → "Alibaba"
"AIAU MARKETS PTY LTD"                            → "AIAU Markets"
"Alibaba.com Singapore E-commerce Pte Ltd"        → "Alibaba"
"PayPal Australia Pty Limited"                    → "PayPal"
"""

import logging
import re
from typing import Optional

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from backend.services.utils import get_llm

log = logging.getLogger(__name__)

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

    cleaned = _rule_clean(raw)
    if not cleaned:
        cleaned = raw

    words = cleaned.split()
    if len(words) <= 3:
        result = _fix_case(cleaned)
        _cache[raw] = result
        return result

    # Still complex after rules — ask the LLM
    try:
        chain = _PROMPT | get_llm().with_structured_output(_NormResult)
        norm: _NormResult = await chain.ainvoke({"vendor": raw})
        result = norm.name.strip() or _fix_case(cleaned)
        log.debug("Vendor normalized | %r → %r", raw, result)
    except Exception as exc:
        log.debug("Vendor normalization LLM failed for %r: %s", raw, exc)
        result = _fix_case(cleaned)

    _cache[raw] = result
    return result
