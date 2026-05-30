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
    date: str = Field(description="Column name for the transaction date")
    vendor: str = Field(
        description="Column with merchant/payee names — must be non-empty in sample rows"
    )
    amount: Optional[str] = Field(
        default=None,
        description="Net/total amount column. null if using separate debit/credit columns. Prefer 'Net' or 'Total' over gross 'Amount'.",
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
        description="Column with human-readable spend categories (e.g. 'Groceries'). null if none.",
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

Rules:
- vendor must be the column containing merchant/payee names (non-empty text, not numbers or dates)
- amount: the net/total amount column; prefer "Net" or "Total" over a gross "Amount" column
- If there are SEPARATE debit and credit columns, set amount=null and use debit_col and credit_col
- description: narrative or memo column; set to the same column as vendor if there is only one text column
- All values must be exact column names from the headers list

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
        chain = _CORE_PROMPT | get_llm().with_structured_output(CSVCoreMappingResult)
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
                   Use for most bank exports
sign_based=false → a column contains explicit labels like "Sale", "Fee", "Refund"
                   Use for PayPal, Stripe, Etsy, marketplace exports

If sign_based=true: set type_col=null and income_types/expense_types/exclude_types=[]

status_col: ONLY set if a column explicitly tracks settlement state (values like "Completed", "Pending", "Cleared")
            Do NOT set status_col to columns named "Type", "Transaction Type", "Method", or "Mode"

invoice_number: ONLY a per-transaction reference (Order #, Invoice #, Confirmation #)
                Do NOT use account numbers, card numbers, or customer IDs

Return ONLY the JSON object."""),
    ("human", "Headers: {headers}\n\nSample rows:\n{sample}"),
])


async def _classification_agent(state: CSVMappingState) -> CSVMappingState:
    headers_str = ", ".join(f'"{h}"' for h in state.headers)
    sample_str = _format_sample(state.sample_rows)
    try:
        chain = _CLASSIFICATION_PROMPT | get_llm().with_structured_output(CSVRowClassificationResult)
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
from backend.services.utils import NUM_RE as _NUM_RE, DATE_RE as _DATE_RE


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


def _build_mapping(state: CSVMappingState) -> dict:
    core = state.core
    cls = state.classification
    hm = state.header_map
    dv = state.all_data_values
    rows = state.sample_rows

    if not core:
        return {}

    # Resolve column names case-insensitively
    date = _resolve(core.date, hm)
    vendor = _resolve(core.vendor, hm)
    amount = _resolve(core.amount, hm)
    debit_col = _resolve(core.debit_col, hm)
    credit_col = _resolve(core.credit_col, hm)
    description = _resolve(core.description, hm)

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

    # Invoice number: block account/card/customer columns
    invoice_number = _resolve(cls.invoice_number, hm)
    if invoice_number and _INVOICE_COL_BLOCK.search(invoice_number):
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
        "category": _resolve(cls.category, hm),
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
    mapping = _build_mapping(final)
    log.info("CSV MAPPING | %s", mapping)
    return mapping
