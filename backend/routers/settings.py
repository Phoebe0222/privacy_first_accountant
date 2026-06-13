from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import AppSettings

router = APIRouter(prefix="/settings", tags=["settings"])

VALID_INCOME_TYPES = ("employment", "business", "both")


def _get(db: Session, key: str, default: str) -> str:
    row = db.get(AppSettings, key)
    return row.value if row else default


def _set(db: Session, key: str, value: str) -> None:
    row = db.get(AppSettings, key)
    if row:
        row.value = value
    else:
        db.add(AppSettings(key=key, value=value))
    db.commit()


@router.get("/tax-profile")
def get_tax_profile(db: Session = Depends(get_db)):
    return {
        "income_type":            _get(db, "income_type",            "both"),
        "gst_registered":         _get(db, "gst_registered",         "false") == "true",
        "gross_salary":           float(_get(db, "gross_salary",     "0")),
        "payg_withheld":          float(_get(db, "payg_withheld",    "0")),
        "private_hospital_cover": _get(db, "private_hospital_cover", "false") == "true",
    }


class TaxProfileUpdate(BaseModel):
    income_type:            str
    gst_registered:         bool
    gross_salary:           float = 0.0
    payg_withheld:          float = 0.0
    private_hospital_cover: bool = False


@router.put("/tax-profile")
def update_tax_profile(body: TaxProfileUpdate, db: Session = Depends(get_db)):
    if body.income_type not in VALID_INCOME_TYPES:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"income_type must be one of {VALID_INCOME_TYPES}")
    _set(db, "income_type",            body.income_type)
    _set(db, "gst_registered",         "true" if body.gst_registered else "false")
    _set(db, "gross_salary",           str(max(0.0, body.gross_salary)))
    _set(db, "payg_withheld",          str(max(0.0, body.payg_withheld)))
    _set(db, "private_hospital_cover", "true" if body.private_hospital_cover else "false")
    return {
        "income_type":            body.income_type,
        "gst_registered":         body.gst_registered,
        "gross_salary":           body.gross_salary,
        "payg_withheld":          body.payg_withheld,
        "private_hospital_cover": body.private_hospital_cover,
    }
