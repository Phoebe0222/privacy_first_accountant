"""
CSV column mapping pipeline using LangChain LCEL.
Replaces the monolithic MAPPING_PROMPT + guards with two focused agents:

  ┌──────────────────────┐
  │  Core Columns Agent  │  date, vendor, amount (or debit/credit), description
  └──────────┬───────────┘
             │
             ▼
  ┌───────────────────────────┐
  │  Row Classification Agent │  sign_based, type_col, income/expense types,
  │                           │  status filter, tax, category, invoice_number
  └───────────────────────────┘
             │
             ▼
       Python resolver
  (column name resolution, list value validation, vendor fallback)
"""

import logging
import os
import re
from typing import Optional

from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from backend.services.utils import get_llm

log = logging.getLogger(__name__)

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
EXTRACT_MODEL = os.getenv("EXTRACT_MODEL", "llama3.2:3b")
CSV_MAP_MODEL = os.getenv("CSV_MAP_MODEL", "llama3.2:3b")


# ── Pipeline state ────────────────────────────────────────────────────────────

class CSVMappingState(BaseModel):
    headers: list[str]
    sample_rows: list[dict]
    header_map: dict[str, str]       # lowercase header → original casing
    all_data_values: set[str]        # all cell values from sample (for list validation)
    core: Optional["CSVCoreMappingResult"] = None
    classification: Optional["CSVRowClassificationResult"] = None

    model_config = {"arbitrary_types_allowed": True}


# ── Structured output schemas ─────────────────────────────────────────────────

class CSVCoreMappingResult(BaseModel):
    date: str = Field(
        description=(
            "The EXACT column name from the headers list containing transaction dates. "
            "For headerless CSVs use the generated name exactly (e.g. 'col_0'), "
            "never a generic word like 'Date'."
        )
    )
    vendor: str = Field(
        description="Column with merchant/payee names — must be non-empty in sample rows"
    )
    amount: Optional[str] = Field(
        default=None,
        description=(
            "The individual transaction amount column. "
            "Set this to null ONLY when there are explicit separate debit and credit columns — "
            "in that case set debit_col and credit_col instead. "
            "For all other formats (signed single amount column) this must NOT be null. "
            "NEVER set this to a Balance or Running Balance column."
        ),
    )
    debit_col: Optional[str] = Field(
        default=None, description="Withdrawal/debit amount column if separate, else null"
    )
    credit_col: Optional[str] = Field(
        default=None, description="Deposit/credit amount column if separate, else null"
    )
    description: Optional[str] = Field(
        default=None,
        description="Narrative/memo column. Can be the same column as vendor if there is only one text column.",
    )


class CSVRowClassificationResult(BaseModel):
    sign_based: bool = Field(
        description=(
            "True if the amount sign determines direction: positive=income, negative=expense. "
            "True for most bank exports. False for PayPal/Stripe/marketplace exports."
        )
    )
    type_col: Optional[str] = Field(
        default=None,
        description="Column with explicit income/expense labels. null if sign_based=true.",
    )
    income_types: list[str] = Field(
        default_factory=list,
        description="Exact type_col values meaning money IN. Empty if sign_based=true.",
    )
    expense_types: list[str] = Field(
        default_factory=list,
        description="Exact type_col values meaning money OUT. Empty if sign_based=true.",
    )
    exclude_types: list[str] = Field(
        default_factory=list,
        description=(
            "Exact type_col values to skip entirely (noise/duplicates). "
            "For PayPal: 'General Authorisation', 'General Credit Card Deposit'."
        ),
    )
    status_col: Optional[str] = Field(
        default=None,
        description=(
            "Column that tracks SETTLEMENT STATE (e.g. 'Status', 'State'). "
            "Do NOT set this to columns named 'Type', 'Transaction Type', or 'Method'. "
            "null if no such column exists."
        ),
    )
    completed_status: Optional[str] = Field(
        default=None,
        description="Exact value in status_col meaning settled (e.g. 'Completed', 'Cleared'). null if no status_col.",
    )
    tax: Optional[str] = Field(
        default=None, description="GST or fee amount column. null if none."
    )
    category: Optional[str] = Field(
        default=None,
        description=(
            "Column with SHORT human-readable spend categories (1–3 words, e.g. 'Groceries', 'Transport', 'Dining'). "
            "null if none. NEVER use a column whose values are long bank descriptions like "
            "'VISA DEBIT PURCHASE CARD 5001 NETFLIX.COM' — those are narrative/description columns, not categories."
        ),
    )
    invoice_number: Optional[str] = Field(
        default=None,
        description=(
            "Per-transaction reference column: Order #, Invoice #, Confirmation #. "
            "Do NOT use account numbers, card numbers, or customer IDs."
        ),
    )


# ── Agent 1: Core column mapping ──────────────────────────────────────────────

_CORE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """\
Map a financial CSV export to standard fields. Return the exact column names as they appear.

Vendor rules (priority order):
  1. "Merchant Name", "Merchant" — bank-assigned clean name, always prefer
  2. "Transaction Details", "Narrative", "Description", "Details", "Memo" — raw bank description
  3. NEVER use these — they are payment metadata, not merchant names:
     "Transaction Type", "Type", "Account Number", "Account", "Bank Account",
     "Card", "Serial", "Reference", "Balance", "Status", "Method", "Category"

Amount rules (IMPORTANT):
  - NEVER set amount to balance, account number, or identifier columns
  - If there are TWO separate debit and credit columns: set amount=null and use debit_col + credit_col
  - For a single signed amount column: set amount to that column (must NOT be null)
  - For headerless CSVs (col_0, col_1, …): col_1 is almost always the transaction amount


Description rules:
  - If vendor is "Merchant Name", set description to the narrative column ("Narrative", "Transaction Details")
  - If there is only one text column, set description = vendor

Date rules:
  - Prefer "Date" over "Processed On", "Settlement Date", "Value Date"
  - For headerless CSVs (col_0, col_1, …): identify the date column by its date-formatted values

All values must be exact column names from the headers list.
Return ONLY the JSON object."""),
    ("human", "Headers: {headers}\n\nSample rows:\n{sample}"),
])


def _format_sample(sample_rows: list[dict], n: int = 5) -> str:
    return "\n".join(
        ", ".join(f'{k}: "{v}"' for k, v in row.items() if v and v != "--")
        for row in sample_rows[:n]
    )


async def _core_agent(state: CSVMappingState) -> CSVMappingState:
    headers_str = ", ".join(f'"{h}"' for h in state.headers)
    sample_str = _format_sample(state.sample_rows)
    try:
        chain = _CORE_PROMPT | get_llm(model=CSV_MAP_MODEL).with_structured_output(CSVCoreMappingResult)
        result: CSVCoreMappingResult = await chain.ainvoke({
            "headers": headers_str,
            "sample": sample_str,
        })
        log.info("Core mapping: date=%s vendor=%s amount=%s debit=%s credit=%s",
                 result.date, result.vendor, result.amount, result.debit_col, result.credit_col)
        return state.model_copy(update={"core": result})
    except Exception as e:
        log.warning("Core columns agent failed: %s", e)
        return state


# ── Agent 2: Row classification mapping ───────────────────────────────────────

_CLASSIFICATION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """\
Analyse how a financial CSV classifies each row as income or expense, and identify filter columns.

sign_based=true  → amount sign determines direction (positive=income, negative=expense)
                   Use for: ANZ, CommBank, NAB single-amount exports; and Westpac (which uses
                   separate Debit/Credit columns — both are positive; direction comes from which
                   column has a value)
sign_based=false → a named column contains explicit labels like "Sale", "Fee", "Refund"
                   Use for: PayPal, Stripe, Etsy, marketplace exports

If sign_based=true: set type_col=null and income_types/expense_types/exclude_types=[]

Westpac note: "Serial" is a transaction serial number — use as invoice_number.
              "Bank Account" is an account identifier — not vendor, not status.

category: if the CSV has a "Category" or "Spend Category" column with human-readable values
          (e.g. "Dining", "Shopping", "Transport") set this. Bank-assigned categories are useful.
          Do NOT set category to columns named "Transaction Type" or "Type".

status_col: ONLY set if a column explicitly tracks settlement state (values like "Completed", "Pending", "Cleared")
            Do NOT set status_col to columns named "Type", "Transaction Type", "Method", "Mode", or "Category"

invoice_number: ONLY a per-transaction reference (Order #, Invoice #, Confirmation #, Transaction ID)
                Do NOT use account numbers, card numbers, customer IDs, or "Account Number"

Return ONLY the JSON object."""),
    ("human", "Headers: {headers}\n\nSample rows:\n{sample}"),
])


async def _classification_agent(state: CSVMappingState) -> CSVMappingState:
    headers_str = ", ".join(f'"{h}"' for h in state.headers)
    sample_str = _format_sample(state.sample_rows)
    try:
        chain = _CLASSIFICATION_PROMPT | get_llm(model=CSV_MAP_MODEL).with_structured_output(CSVRowClassificationResult)
        result: CSVRowClassificationResult = await chain.ainvoke({
            "headers": headers_str,
            "sample": sample_str,
        })
        log.info("Classification: sign_based=%s type_col=%s status_col=%s",
                 result.sign_based, result.type_col, result.status_col)
        return state.model_copy(update={"classification": result})
    except Exception as e:
        log.warning("Classification agent failed: %s", e)
        return state


# ── LCEL pipeline ─────────────────────────────────────────────────────────────

_pipeline = RunnableLambda(_core_agent) | RunnableLambda(_classification_agent)


# ── Python post-processor ─────────────────────────────────────────────────────

_STATUS_COL_BLOCK = re.compile(r"\btype\b|\bmethod\b|\bmode\b", re.IGNORECASE)
_INVOICE_COL_BLOCK = re.compile(r"\baccount\b|\bcard\b|\bcustomer\b|\bclient\b|\buser\b", re.IGNORECASE)
_VENDOR_COL_BLOCK = re.compile(
    r"\btransaction\s+type\b|\btype\b|\bmethod\b|\bstatus\b|\bbalance\b|\bcategory\b"
    r"|\baccount\s+number\b|\bbank\s+account\b|\bserial\b",
    re.IGNORECASE,
)
from backend.services.utils import NUM_RE as _NUM_RE, DATE_RE as _DATE_RE

# ── Pattern-based column detection (authoritative for well-known names) ────────

_AMOUNT_NAMES    = re.compile(r"^amount$|^net$|^total$", re.IGNORECASE)
_DEBIT_NAMES     = re.compile(r"\bdebit\b", re.IGNORECASE)
_CREDIT_NAMES    = re.compile(r"\bcredit\b", re.IGNORECASE)
_BALANCE_NAMES   = re.compile(r"\bbalance\b|\brunning\b", re.IGNORECASE)
_DATE_NAMES      = re.compile(r"^date$|^transaction\s*date$|^trans\s*date$", re.IGNORECASE)
_VENDOR_PRIORITY = [
    re.compile(r"^merchant\s*name$|^merchant$", re.IGNORECASE),
    re.compile(r"^narrative$|^transaction\s+details$|^description$|^details$|^memo$", re.IGNORECASE),
]


def _detect_from_patterns(headers: list[str], rows: list[dict]) -> dict:
    """
    Detect key columns from header names and data patterns.
    Returns a partial mapping — only fields we're confident about.
    """
    result: dict = {}

    # ── Date: named first, then data scan ────────────────────────────────────
    for h in headers:
        if _DATE_NAMES.match(h):
            result["date"] = h
            break
    if "date" not in result:
        for h in headers:
            vals = [row.get(h, "").strip() for row in rows[:5] if row.get(h, "").strip()]
            if vals and _DATE_RE.match(vals[0]):
                result["date"] = h
                break

    # ── Amount / debit+credit ─────────────────────────────────────────────────
    debit_h  = next((h for h in headers if _DEBIT_NAMES.search(h)), None)
    credit_h = next((h for h in headers if _CREDIT_NAMES.search(h)), None)
    if debit_h and credit_h:
        result["debit_col"] = debit_h
        result["credit_col"] = credit_h
    else:
        # Named "Amount" / "Net" / "Total"
        amount_h = next((h for h in headers if _AMOUNT_NAMES.match(h)), None)
        if amount_h:
            result["amount"] = amount_h
        else:
            # Headerless: first numeric column after the date column
            date_h = result.get("date")
            seen_date = False
            for h in headers:
                if h == date_h:
                    seen_date = True
                    continue
                if not seen_date:
                    continue
                if _BALANCE_NAMES.search(h):
                    continue
                vals = [row.get(h, "").strip() for row in rows[:10] if row.get(h, "").strip()]
                monetary = [v for v in vals if _NUM_RE.match(re.sub(r'[,$+]', '', v.lstrip('-')))]
                if len(monetary) >= max(1, len(vals) // 2):
                    result["amount"] = h
                    break

    # ── Vendor: priority list of known column names ───────────────────────────
    for pattern in _VENDOR_PRIORITY:
        h = next((h for h in headers if pattern.match(h)), None)
        if h:
            result["vendor"] = h
            result["description"] = h
            break

    return result


def _resolve(name: Optional[str], header_map: dict[str, str]) -> Optional[str]:
    """Resolve a column name case-insensitively; return None if not a real header."""
    if not name or not isinstance(name, str):
        return None
    if name.strip().lower() == "null":
        return None
    return header_map.get(name.lower().strip())


def _filter_list(values: list[str], all_data_values: set[str]) -> list[str]:
    """Keep only values that actually appear in the sample data."""
    return [v for v in values if isinstance(v, str) and v.strip().lower() in all_data_values]


def _validate_category_col(col: Optional[str], rows: list[dict]) -> Optional[str]:
    """Reject a category column whose values look like raw bank descriptions rather than
    short human-readable categories (e.g. 'Groceries', 'Transport').
    A value with more than 4 words is almost certainly a description, not a category."""
    if not col:
        return None
    sample_vals = [row.get(col, "").strip() for row in rows[:10] if row.get(col, "").strip()]
    if not sample_vals:
        return col
    avg_words = sum(len(v.split()) for v in sample_vals) / len(sample_vals)
    if avg_words > 4:
        return None
    return col


def _build_mapping(state: CSVMappingState) -> dict:
    core = state.core
    cls = state.classification
    hm = state.header_map
    dv = state.all_data_values
    rows = state.sample_rows

    if not core:
        return {}

    # Run pattern-based detection — authoritative for well-known column names.
    # These override the LLM where we're confident (named "Amount", "Debit Amount", etc.)
    patterns = _detect_from_patterns(state.headers, rows)
    log.debug("Pattern detection: %s", patterns)

    # Resolve LLM output, then fill gaps / overrides from patterns
    date      = _resolve(core.date, hm)      or patterns.get("date")
    vendor    = _resolve(core.vendor, hm)    or patterns.get("vendor")
    amount    = patterns.get("amount")       or _resolve(core.amount, hm)
    debit_col = patterns.get("debit_col")    or _resolve(core.debit_col, hm)
    credit_col= patterns.get("credit_col")   or _resolve(core.credit_col, hm)
    description = _resolve(core.description, hm) or patterns.get("description")

    # If pattern detected debit+credit, clear single amount
    if debit_col and credit_col:
        amount = None

    # ── General data-driven validation ──────────────────────────────────────────
    # Rather than bank-specific guards, validate each field against actual sample values.

    # Amount validation: if the LLM-mapped amount column contains non-monetary values
    # (e.g. account numbers, text), clear it so the fallback can find the right column.
    if amount:
        sample_vals = [row.get(amount, "").strip() for row in rows[:10] if row.get(amount, "").strip()]
        monetary = [v for v in sample_vals if _NUM_RE.match(re.sub(r'[,$]', '', v.lstrip('-').lstrip('+')))]
        if len(monetary) < len(sample_vals) // 2:
            log.warning("Amount column '%s' contains non-monetary values — clearing", amount)
            amount = None

    # Vendor guard: reject columns that are clearly metadata, not merchant names
    if vendor and _VENDOR_COL_BLOCK.search(vendor):
        log.warning("Vendor column '%s' looks like metadata — clearing, fallback will find better", vendor)
        vendor = None

    # Vendor fallback: if the resolved vendor column is empty in sample rows, find a better one
    def _has_values(col: Optional[str]) -> bool:
        return bool(col and any(row.get(col, "").strip() for row in rows[:10]))

    if not _has_values(vendor):
        reserved = {date, amount, debit_col, credit_col}
        for h in state.headers:
            if h in reserved:
                continue
            vals = [row.get(h, "").strip() for row in rows[:10] if row.get(h, "").strip()]
            if vals and not _NUM_RE.match(vals[0]) and not _DATE_RE.match(vals[0]):
                vendor = h
                break

    # Description fallback
    if not description and vendor:
        description = vendor

    if not cls:
        return {
            "date": date, "vendor": vendor, "amount": amount,
            "debit_col": debit_col, "credit_col": credit_col, "description": description,
            "type_col": None, "income_types": [], "expense_types": [], "exclude_types": [],
            "status_col": None, "completed_status": None,
            "tax": None, "category": None, "invoice_number": None,
        }

    # If sign_based, wipe type classification fields (model should already do this, safety net)
    if cls.sign_based:
        type_col = None
        income_types: list[str] = []
        expense_types: list[str] = []
        exclude_types: list[str] = []
    else:
        type_col = _resolve(cls.type_col, hm)
        income_types = _filter_list(cls.income_types, dv)
        expense_types = _filter_list(cls.expense_types, dv)
        exclude_types = _filter_list(cls.exclude_types, dv)
        # If we ended up with no types after filtering, fall back to sign-based
        if not income_types and not expense_types:
            type_col = None

    # Status column: block name patterns that indicate a type/method column, not status
    status_col = _resolve(cls.status_col, hm)
    completed_status = cls.completed_status
    if status_col and _STATUS_COL_BLOCK.search(status_col):
        status_col = None
        completed_status = None
    # Sanity check: completed_status must actually appear in the data
    if status_col and completed_status:
        if not any(row.get(status_col, "").strip().lower() == completed_status.lower() for row in rows):
            status_col = None
            completed_status = None

    # Invoice number: block account/card/customer columns and date columns
    invoice_number = _resolve(cls.invoice_number, hm)
    if invoice_number and _INVOICE_COL_BLOCK.search(invoice_number):
        invoice_number = None
    # Never use the date column as invoice_number (LLM confusion with headerless CSVs)
    if invoice_number and invoice_number == date:
        invoice_number = None

    return {
        "date": date,
        "vendor": vendor,
        "amount": amount,
        "debit_col": debit_col,
        "credit_col": credit_col,
        "description": description,
        "type_col": type_col,
        "income_types": income_types,
        "expense_types": expense_types,
        "exclude_types": exclude_types,
        "status_col": status_col,
        "completed_status": completed_status,
        "tax": _resolve(cls.tax, hm),
        "category": _validate_category_col(_resolve(cls.category, hm), rows),
        "invoice_number": invoice_number,
    }


# ── Public API ────────────────────────────────────────────────────────────────

async def map_csv_columns(headers: list[str], sample_rows: list[dict]) -> dict:
    """
    Run the 2-agent CSV column mapping pipeline.
    Returns a mapping dict compatible with csv_ingestion.apply_mapping().
    """
    header_map = {h.lower().strip(): h for h in headers}
    all_data_values: set[str] = {
        v.strip().lower()
        for row in sample_rows[:20]
        for v in row.values()
        if v and v != "--"
    }
    state = CSVMappingState(
        headers=headers,
        sample_rows=sample_rows,
        header_map=header_map,
        all_data_values=all_data_values,
    )
    final: CSVMappingState = await _pipeline.ainvoke(state)

    # Log raw LLM output before any guards/fallbacks
    if final.core:
        c = final.core
        log.info(
            "CSV LLM RAW (core) | date=%s vendor=%s amount=%s debit=%s credit=%s description=%s",
            c.date, c.vendor, c.amount, c.debit_col, c.credit_col, c.description,
        )
    if final.classification:
        cls = final.classification
        log.info(
            "CSV LLM RAW (classification) | sign_based=%s type_col=%s category=%s invoice=%s",
            cls.sign_based, cls.type_col, cls.category, cls.invoice_number,
        )

    mapping = _build_mapping(final)
    log.info("CSV MAPPING (after guards) | %s", mapping)
    return mapping
