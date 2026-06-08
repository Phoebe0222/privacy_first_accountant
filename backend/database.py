import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

_DATA_DIR = Path(__file__).parent.parent / "data"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_DATA_DIR / 'accountant.db'}")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_DEDUCTION_SEEDS = {
    "individual_salary": [
        ("transport",   0.8, "Work-related travel",            "Logbook required for car"),
        ("office",      1.0, "Work equipment & supplies",      "Must be work-related"),
        ("software",    0.8, "Work-related software",          "Work-use portion only"),
        ("subscription",0.5, "Partial work use",               "Estimate — review individually"),
        ("home_office", 1.0, "Home office running costs",      "ATO fixed rate 67c/hr or actual"),
        ("other",       0.3, "Review individually",            None),
    ],
    "individual_abn": [
        ("software",    1.0, "Business software",              None),
        ("subscription",1.0, "Business subscriptions",         None),
        ("marketing",   1.0, "Marketing & advertising",        None),
        ("office",      1.0, "Office expenses",                None),
        ("transport",   0.8, "Business travel",                "Logbook required for car"),
        ("utilities",   0.5, "Business-use portion",           "Home office or studio"),
        ("home_office", 1.0, "Home office running costs",      "ATO fixed rate 67c/hr or actual"),
        ("food",        0.5, "Client entertainment",           "50% meal entertainment rule"),
        ("other",       0.5, "Estimated — review individually",None),
    ],
    "small_business": [
        ("software",    1.0, "Business software",              None),
        ("subscription",1.0, "Business subscriptions",         None),
        ("marketing",   1.0, "Marketing & advertising",        None),
        ("office",      1.0, "Office expenses",                None),
        ("transport",   0.8, "Business travel",                "Logbook required for car"),
        ("utilities",   0.5, "Business portion of utilities",  None),
        ("home_office", 1.0, "Home office running costs",      "ATO fixed rate 67c/hr or actual"),
        ("food",        0.5, "Client entertainment",           "50% meal entertainment rule"),
        ("salary",      1.0, "Wages paid to employees",        None),
        ("material",    1.0, "Cost of goods / materials",      None),
        ("fee",         1.0, "Bank fees & service charges",    None),
        ("other",       0.5, "Estimated — review individually",None),
    ],
}


def init_db():
    from backend.models import Transaction, EmailAccount, ChatMessage, VendorRule, ATORule, Attachment, ReconciliationMatch, DeductionRule, AppSettings, AITaxCache  # noqa: F401
    Base.metadata.create_all(bind=engine)
    # Add new columns to existing tables without dropping data
    with engine.connect() as conn:
        for col, definition in [
            ("anomaly", "BOOLEAN DEFAULT 0"),
            ("anomaly_reason", "VARCHAR"),
            ("needs_review", "BOOLEAN DEFAULT 0"),
            ("category_confidence", "REAL"),
            ("business", "BOOLEAN DEFAULT 0"),
            ("tax_kind", "VARCHAR DEFAULT 'na'"),
        ]:
            try:
                conn.execute(__import__("sqlalchemy").text(
                    f"ALTER TABLE transactions ADD COLUMN {col} {definition}"
                ))
                conn.commit()
            except Exception:
                pass  # Column already exists

        # Backfill tax_kind from existing business flag; collapse personal → na
        try:
            _text = __import__("sqlalchemy").text
            conn.execute(_text("UPDATE transactions SET tax_kind = 'business' WHERE business = 1 AND (tax_kind IS NULL OR tax_kind != 'business')"))
            conn.execute(_text("UPDATE transactions SET tax_kind = 'na' WHERE (tax_kind IS NULL OR tax_kind = 'personal')"))
            conn.commit()
        except Exception:
            pass

    # Add built_in column to vendor_rules if missing
    with engine.connect() as conn:
        try:
            conn.execute(__import__("sqlalchemy").text(
                "ALTER TABLE vendor_rules ADD COLUMN built_in BOOLEAN DEFAULT 0"
            ))
            conn.commit()
        except Exception:
            pass

    # Seed default deduction rules if table is empty
    db = SessionLocal()
    try:
        if db.query(DeductionRule).count() == 0:
            for user_type, rules in _DEDUCTION_SEEDS.items():
                for category, rate, label, note in rules:
                    db.add(DeductionRule(
                        user_type=user_type, category=category,
                        rate=rate, label=label, note=note,
                    ))
            db.commit()
        # Seed default user_type setting if not set
        if not db.get(AppSettings, "user_type"):
            db.add(AppSettings(key="user_type", value="small_business"))
            db.commit()
        if not db.get(AppSettings, "income_type"):
            db.add(AppSettings(key="income_type", value="both"))
            db.commit()
        if not db.get(AppSettings, "gst_registered"):
            db.add(AppSettings(key="gst_registered", value="false"))
            db.commit()

        # Seed built-in vendor rules if none exist yet
        if db.query(VendorRule).filter(VendorRule.built_in == True).count() == 0:  # noqa: E712
            from backend.services._builtin_rules import BUILT_IN_RULES
            for pattern, category in BUILT_IN_RULES:
                db.add(VendorRule(vendor_pattern=pattern, category=category, built_in=True))
            db.commit()
    finally:
        db.close()
