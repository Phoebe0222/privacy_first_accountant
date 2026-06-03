import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./accountant.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_DEFAULT_DEDUCTION_RULES = {
    "individual_salary": [
        ("transport",    0.8, "Transport",             "Work-related travel (logbook required)"),
        ("office",       1.0, "Office Supplies",       "Work-related equipment and supplies"),
        ("software",     0.8, "Software",              "Work-related software only"),
        ("subscription", 0.5, "Subscriptions",         "Partial work use estimated"),
        ("home_office",  1.0, "Home Office",           "ATO 67c/hr fixed rate or actual cost method"),
        ("other",        0.3, "Other Expenses",        "Review individually"),
    ],
    "individual_abn": [
        ("software",     1.0, "Software & Tools",      "100% deductible for business use"),
        ("subscription", 1.0, "Subscriptions",         "100% deductible for business use"),
        ("marketing",    1.0, "Marketing",             "100% deductible"),
        ("office",       1.0, "Office Supplies",       "100% deductible"),
        ("transport",    0.8, "Transport",             "Business travel (logbook required)"),
        ("utilities",    0.5, "Utilities",             "Business-use portion"),
        ("home_office",  1.0, "Home Office",           "ATO 67c/hr fixed rate or actual cost method"),
        ("food",         0.5, "Meals & Entertainment", "50% for client entertainment"),
        ("other",        0.5, "Other Expenses",        "Estimated — review individually"),
    ],
    "small_business": [
        ("software",     1.0, "Software & Tools",      "100% deductible"),
        ("subscription", 1.0, "Subscriptions",         "100% deductible"),
        ("marketing",    1.0, "Marketing",             "100% deductible"),
        ("office",       1.0, "Office Supplies",       "100% deductible"),
        ("transport",    0.8, "Transport",             "Business travel"),
        ("utilities",    0.5, "Utilities",             "Business-use portion"),
        ("home_office",  1.0, "Home Office",           "ATO 67c/hr fixed rate or actual cost method"),
        ("food",         0.5, "Meals & Entertainment", "50% — client entertainment"),
        ("salary",       1.0, "Wages & Salaries",      "100% deductible"),
        ("other",        0.5, "Other Expenses",        "Estimated — review individually"),
    ],
}


def seed_deduction_rules(db):
    from backend.models import DeductionRule, AppSettings
    if db.query(DeductionRule).count() > 0:
        return
    for user_type, rules in _DEFAULT_DEDUCTION_RULES.items():
        for category, rate, label, note in rules:
            db.add(DeductionRule(user_type=user_type, category=category, rate=rate, label=label, note=note))
    if not db.get(AppSettings, "user_type"):
        db.add(AppSettings(key="user_type", value="small_business"))
    db.commit()


def init_db():
    from backend.models import Transaction, EmailAccount, ChatMessage, DeductionRule, AppSettings  # noqa: F401
    Base.metadata.create_all(bind=engine)
    # Add new columns to existing tables without dropping data
    with engine.connect() as conn:
        for col, definition in [
            ("anomaly",        "BOOLEAN DEFAULT 0"),
            ("anomaly_reason", "VARCHAR"),
            ("business",       "BOOLEAN DEFAULT 1"),
        ]:
            try:
                conn.execute(__import__("sqlalchemy").text(
                    f"ALTER TABLE transactions ADD COLUMN {col} {definition}"
                ))
                conn.commit()
            except Exception:
                pass  # Column already exists

    db = SessionLocal()
    try:
        seed_deduction_rules(db)
    finally:
        db.close()
