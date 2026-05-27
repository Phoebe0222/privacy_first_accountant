import csv
import io
import re


_DATE_RE = re.compile(r"^\d{1,4}[-/]\d{1,2}[-/]\d{2,4}$|^\d{1,2}\s+\w+\s+\d{2,4}$")
_NUMBER_RE = re.compile(r'^-?\s*["$]?[\d,]+\.?\d*$')


def _looks_like_data_row(row: list[str]) -> bool:
    """Return True if the first row appears to be data rather than headers."""
    if not row:
        return False
    first = row[0].strip().strip('"')
    return bool(_DATE_RE.match(first) or _NUMBER_RE.match(first))


def parse_csv(file_bytes: bytes, filename: str = "") -> tuple[list[str], list[dict]]:
    if filename.lower().endswith((".xlsx", ".xls")):
        return _parse_excel(file_bytes)
    text = file_bytes.decode("utf-8-sig", errors="replace")
    raw_reader = csv.reader(io.StringIO(text))
    first_row = next(raw_reader, None)
    if first_row is None:
        return [], []
    if _looks_like_data_row(first_row):
        # No headers — generate col_0, col_1, …
        headers = [f"col_{i}" for i in range(len(first_row))]
        all_rows = [first_row] + list(raw_reader)
    else:
        headers = [h.strip() for h in first_row]
        all_rows = list(raw_reader)
    rows = [
        {headers[i]: cell.strip() for i, cell in enumerate(row) if i < len(headers)}
        for row in all_rows
    ]
    return headers, rows


def _parse_excel(file_bytes: bytes) -> tuple[list[str], list[dict]]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = iter(ws.rows)
    header_row = next(rows_iter, None)
    if header_row is None:
        return [], []
    headers = [str(cell.value).strip() if cell.value is not None else f"col_{i}" for i, cell in enumerate(header_row)]
    rows = []
    for row in rows_iter:
        row_dict = {
            headers[i]: (str(cell.value).strip() if cell.value is not None else "")
            for i, cell in enumerate(row) if i < len(headers)
        }
        rows.append(row_dict)
    wb.close()
    return headers, rows


def _clean_amount(raw: str) -> float:
    """Parse amount strings from any common format."""
    raw = raw.strip()
    if not raw or raw == "--":
        return 0.0
    # Remove currency symbols and codes (AU$, $, £, €, USD, AUD, etc.)
    raw = re.sub(r'[A-Z]{0,3}\$|[£€]', '', raw)
    raw = raw.replace(",", "").replace(" ", "")
    # Accounting negatives: (1234.56) → -1234.56
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1]
    try:
        return float(raw)
    except ValueError:
        return 0.0


def apply_mapping(rows: list[dict], mapping: dict) -> list[dict]:
    transactions = []
    type_col = mapping.get("type_col")
    income_types = {v.lower() for v in (mapping.get("income_types") or []) if v}
    expense_types = {v.lower() for v in (mapping.get("expense_types") or []) if v}
    exclude_types = {v.lower() for v in (mapping.get("exclude_types") or []) if v}
    status_col = mapping.get("status_col")
    completed_status = (mapping.get("completed_status") or "").lower().strip()
    credit_col = mapping.get("credit_col")
    debit_col = mapping.get("debit_col")
    amount_col = mapping.get("amount")

    for row in rows:
        def get(field, r=row):
            col = mapping.get(field)
            return r.get(col, "").strip() if col and col in r else ""

        # ── Skip rows that don't match the required status ───────────────────
        if status_col and completed_status and status_col in row:
            if row[status_col].strip().lower() != completed_status:
                continue

        # ── Skip excluded type values (noise/duplicates) ─────────────────────
        if type_col and exclude_types and type_col in row:
            if row[type_col].strip().lower() in exclude_types:
                continue

        # ── Determine amount and type ────────────────────────────────────────
        if credit_col and debit_col:
            credit = _clean_amount(row.get(credit_col, ""))
            debit = _clean_amount(row.get(debit_col, ""))
            if credit > 0:
                tx_type, amount = "income", credit
            elif debit > 0:
                tx_type, amount = "expense", debit
            else:
                continue
        else:
            amount_raw = row.get(amount_col, "") if amount_col else ""
            amount_val = _clean_amount(amount_raw)
            if amount_val == 0:
                continue

            if type_col and type_col in row:
                type_val = row[type_col].strip().lower()
                if type_val in income_types:
                    tx_type = "income"
                elif type_val in expense_types:
                    tx_type = "expense"
                else:
                    # Unknown type value — fall back to sign
                    tx_type = "income" if amount_val > 0 else "expense"
            else:
                tx_type = "income" if amount_val > 0 else "expense"

            amount = abs(amount_val)

        date = get("date") or ""
        vendor = get("vendor") or "Unknown"

        transactions.append({
            "date": _normalise_date(date),
            "vendor": vendor[:200],
            "amount": round(amount, 2),
            "tax": round(abs(_clean_amount(get("tax"))), 2),
            "type": tx_type,
            "category": get("category") or "other",
            "description": (get("description") or vendor)[:500],
            "invoice_number": get("invoice_number") or None,
        })
    return transactions


def _normalise_date(raw: str) -> str:
    from datetime import datetime
    raw = raw.strip()
    # Remove trailing time component (e.g. "2026-04-15 01:23:21" or "2026-04-15T14:00:00")
    raw = re.sub(r"[T ]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$", "", raw).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y",
                "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
                "%d %b %y", "%d %B %y",
                "%Y/%m/%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw
