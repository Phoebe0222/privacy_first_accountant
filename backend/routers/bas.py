from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Transaction

router = APIRouter(prefix="/bas", tags=["bas"])

# Australian financial year: Q1=Jul-Sep, Q2=Oct-Dec, Q3=Jan-Mar, Q4=Apr-Jun
# `fy` param = the year in which June falls (e.g. fy=2025 → Jul 2024 – Jun 2025)
_QUARTER_RANGES = {
    "Q1":     (lambda fy: (f"{fy - 1}-07-01", f"{fy - 1}-09-30")),
    "Q2":     (lambda fy: (f"{fy - 1}-10-01", f"{fy - 1}-12-31")),
    "Q3":     (lambda fy: (f"{fy}-01-01",     f"{fy}-03-31")),
    "Q4":     (lambda fy: (f"{fy}-04-01",     f"{fy}-06-30")),
    "annual": (lambda fy: (f"{fy - 1}-07-01", f"{fy}-06-30")),
}

# Sources considered primary financial records (not reconciliation)
_PRIMARY_SOURCES = ("bank_csv", "manual")


@router.get("")
def get_bas(fy: int, quarter: str = "Q1", db: Session = Depends(get_db)):
    if quarter not in _QUARTER_RANGES:
        raise HTTPException(status_code=400, detail=f"quarter must be one of: {', '.join(_QUARTER_RANGES)}")

    date_start, date_end = _QUARTER_RANGES[quarter](fy)

    q = (
        db.query(Transaction)
        .filter(
            Transaction.source.in_(_PRIMARY_SOURCES),
            Transaction.business == True,  # noqa: E712
            Transaction.date >= date_start,
            Transaction.date <= date_end,
        )
    )

    rows = q.all()
    income_rows = [t for t in rows if t.type == "income"]
    expense_rows = [t for t in rows if t.type == "expense"]

    G1 = round(sum(t.amount for t in income_rows), 2)
    G11 = round(sum(t.amount for t in expense_rows), 2)
    tax_1A = round(sum(t.tax or 0 for t in income_rows), 2)
    tax_1B = round(sum(t.tax or 0 for t in expense_rows), 2)
    net_gst = round(tax_1A - tax_1B, 2)

    # Annualise G1 to check GST registration threshold ($75k)
    quarters_in_period = 4 if quarter == "annual" else 1
    annualised_income = G1 * (4 / quarters_in_period)
    gst_registration_warning = annualised_income >= 75000

    period_label = f"FY{fy} {quarter}" if quarter != "annual" else f"FY{fy} Annual"

    return {
        "period": period_label,
        "fy": fy,
        "quarter": quarter,
        "date_range": f"{date_start} to {date_end}",
        "G1": G1,
        "G11": G11,
        "tax_1A": tax_1A,
        "tax_1B": tax_1B,
        "net_gst": net_gst,
        "transaction_count": len(rows),
        "gst_registration_warning": gst_registration_warning,
    }
