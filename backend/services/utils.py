import os
import re
from typing import Optional


# ── Shared regex patterns ─────────────────────────────────────────────────────

DATE_RE = re.compile(r"^\d{1,4}[-/]\d{1,2}[-/]\d{2,4}$|^\d{1,2}\s+\w+\s+\d{2,4}$")
NUM_RE = re.compile(r'^-?\s*["$]?[\d,]+\.?\d*$')


# ── LLM factory (cached per model+temperature) ────────────────────────────────

try:
    from langchain_ollama import ChatOllama
    _llm_cache: dict[str, "ChatOllama"] = {}

    def get_llm(model: Optional[str] = None, temperature: int = 0) -> "ChatOllama":
        _model = model or os.getenv("EXTRACT_MODEL", "llama3.2:3b")
        _base = os.getenv("OLLAMA_BASE", "http://localhost:11434")
        key = f"{_model}:{temperature}"
        if key not in _llm_cache:
            _llm_cache[key] = ChatOllama(model=_model, temperature=temperature, base_url=_base)
        return _llm_cache[key]

except ImportError:
    def get_llm(model: Optional[str] = None, temperature: int = 0):  # type: ignore[misc]
        raise RuntimeError("langchain-ollama is not installed")


# ── Date normalisation ────────────────────────────────────────────────────────

_MONTH_ALIASES = {
    "jan": "Jan", "feb": "Feb", "mar": "Mar", "apr": "Apr",
    "may": "May", "jun": "Jun", "jul": "Jul", "aug": "Aug",
    "sept": "Sep", "sep": "Sep", "oct": "Oct", "nov": "Nov", "dec": "Dec",
    "january": "January", "february": "February", "march": "March",
    "april": "April", "june": "June", "july": "July", "august": "August",
    "september": "September", "october": "October", "november": "November",
    "december": "December",
}


def normalise_date(raw: str) -> str:
    from datetime import datetime
    raw = raw.strip()
    raw = re.sub(r"[T ]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$", "", raw).strip()
    raw = re.sub(
        r"\b([A-Za-z]+)\b",
        lambda m: _MONTH_ALIASES.get(m.group(1).lower(), m.group(1)),
        raw,
    )
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y",
                "%d/%m/%y", "%m/%d/%y", "%d-%m-%y",
                "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
                "%d %b %y", "%d %B %y",
                "%Y/%m/%d", "%d-%b-%Y", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw
