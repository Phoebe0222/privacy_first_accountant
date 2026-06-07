"""
BAS (Business Activity Statement) estimation endpoint.

Covers Australian quarterly and annual reporting periods.
Only counts primary-record transactions: source IN ("bank_csv", "manual")
AND business == True. Email/PDF/image/csv are reconciliation sources only.

Australian financial year quarters:
  Q1  Jul – Sep
  Q2  Oct – Dec
  Q3  Jan – Mar
  Q4  Apr – Jun
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Transaction

router = APIRouter(prefix="/bas", tags=["bas"])

_PRIMARY_SOURCES = ("bank_csv", "manual")
GST_THRESHOLD = 75_000.0


def _quarter_dates(year: int, quarter: str) -> tuple[str, str]:
    """Return (date_from, date_to) for an Australian financial year quarter.
    `year` is the calendar year in which July falls (i.e. the FY start year).
    """
    ranges = {
        "Q1": (f"{year}-07-01",     f"{year}-09-30"),
        "Q2": (f"{year}-10-01",     f"{year}-12-31"),
        "Q3": (f"{year + 1}-01-01", f"{year + 1}-03-31"),
        "Q4": (f"{year + 1}-04-01", f"{year + 1}-06-30"),
        "annual": (f"{year}-07-01", f"{year + 1}-06-30"),
    }
    if quarter not in ranges:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid quarter '{quarter}'. Use Q1, Q2, Q3, Q4, or annual.",
        )
    return ranges[quarter]


@router.get("")
def get_bas(year: int, quarter: str = "annual", db: Session = Depends(get_db)):
    """
    Calculate BAS figures for a given Australian financial year and quarter.
    `year` is the FY start year (e.g. year=2025 → FY 2025-26).
    """
    date_from, date_to = _quarter_dates(year, quarter)

    base_q = (
        db.query(Transaction)
        .filter(
            Transaction.source.in_(_PRIMARY_SOURCES),
            Transaction.tax_kind == "business",
            Transaction.date >= date_from,
            Transaction.date <= date_to,
        )
    )

    # G1 is taxable supplies only — sales of products/services.
    # Revenue (dividends, rent), salary, and refunds are excluded.
    income_txs = base_q.filter(
        Transaction.type == "income",
        Transaction.category == "sales",
    ).all()
    expense_txs = base_q.filter(Transaction.type == "expense").all()

    G1 = sum(t.amount or 0 for t in income_txs)
    G11 = sum(t.amount or 0 for t in expense_txs)
    tax_1A = sum(t.tax or 0 for t in income_txs)   # GST collected on sales
    tax_1B = sum(t.tax or 0 for t in expense_txs)   # Input tax credits on purchases
    net_gst = round(tax_1A - tax_1B, 2)

    # Annualise G1 to check GST registration threshold
    multiplier = {"Q1": 4, "Q2": 4, "Q3": 4, "Q4": 4, "annual": 1}.get(quarter, 1)
    annualised_g1 = G1 * multiplier
    gst_registration_warning = annualised_g1 >= GST_THRESHOLD

    return {
        "period": f"FY{year}-{str(year + 1)[2:]} {quarter}",
        "date_range": f"{date_from} to {date_to}",
        "G1": round(G1, 2),
        "G11": round(G11, 2),
        "tax_1A": round(tax_1A, 2),
        "tax_1B": round(tax_1B, 2),
        "net_gst": net_gst,
        "transaction_count": len(income_txs) + len(expense_txs),
        "gst_registration_warning": gst_registration_warning,
        "annualised_income": round(annualised_g1, 2),
    }
