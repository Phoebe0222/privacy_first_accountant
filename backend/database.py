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


def init_db():
    from backend.models import Transaction, EmailAccount, ChatMessage, VendorRule, ATORule  # noqa: F401
    Base.metadata.create_all(bind=engine)
    # Add new columns to existing tables without dropping data
    with engine.connect() as conn:
        for col, definition in [
            ("anomaly", "BOOLEAN DEFAULT 0"),
            ("anomaly_reason", "VARCHAR"),
            ("needs_review", "BOOLEAN DEFAULT 0"),
            ("category_confidence", "REAL"),
        ]:
            try:
                conn.execute(__import__("sqlalchemy").text(
                    f"ALTER TABLE transactions ADD COLUMN {col} {definition}"
                ))
                conn.commit()
            except Exception:
                pass  # Column already exists
