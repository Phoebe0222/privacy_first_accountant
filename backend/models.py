from datetime import datetime
from sqlalchemy import Boolean, Column, ForeignKey, Integer, LargeBinary, String, Float, Text, DateTime
from backend.database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String, index=True)
    vendor = Column(String, index=True)
    amount = Column(Float, nullable=False)
    tax = Column(Float, default=0.0)
    category = Column(String, index=True)
    type = Column(String)  # "income" or "expense"
    source = Column(String)  # "email", "pdf", "image", "manual"
    source_ref = Column(String, nullable=True)
    description = Column(String, nullable=True)
    invoice_number = Column(String, nullable=True)
    raw_text = Column(Text, nullable=True)
    anomaly = Column(Boolean, default=False, nullable=True)
    anomaly_reason = Column(String, nullable=True)
    needs_review = Column(Boolean, default=False, nullable=True)
    category_confidence = Column(Float, nullable=True)
    business = Column(Boolean, default=False, nullable=True)
    tax_kind = Column(String, default="na", nullable=True)  # "business" | "employment" | "na"
    created_at = Column(DateTime, default=datetime.utcnow)


class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String, nullable=True)
    mime_type = Column(String, nullable=False)
    data = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class EmailAccount(Base):
    __tablename__ = "email_accounts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, unique=True)
    imap_host = Column(String)
    imap_port = Column(Integer, default=993)
    username = Column(String)
    password = Column(String)
    last_synced = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    role = Column(String)  # "user" or "assistant"
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class VendorRule(Base):
    __tablename__ = "vendor_rules"

    id = Column(Integer, primary_key=True, index=True)
    vendor_pattern = Column(String, nullable=False)
    category = Column(String, nullable=False)
    built_in = Column(Boolean, default=False, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ATORule(Base):
    __tablename__ = "ato_rules"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class DeductionRule(Base):
    __tablename__ = "deduction_rules"

    id = Column(Integer, primary_key=True, index=True)
    user_type = Column(String, nullable=False)   # "individual_salary" | "individual_abn" | "small_business"
    category = Column(String, nullable=False)
    rate = Column(Float, nullable=False)          # 0.0–1.0
    label = Column(String, nullable=False)
    note = Column(String, nullable=True)


class AppSettings(Base):
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=True)


class AITaxCache(Base):
    __tablename__ = "ai_tax_cache"

    year = Column(Integer, primary_key=True)
    result_json = Column(Text, nullable=False)
    computed_at = Column(DateTime, default=datetime.utcnow)


class ReconciliationMatch(Base):
    __tablename__ = "reconciliation_matches"

    id = Column(Integer, primary_key=True, index=True)
    bank_tx_id = Column(Integer, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    receipt_tx_id = Column(Integer, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    confidence = Column(Float, nullable=False)
    status = Column(String, default="auto")  # "auto" | "confirmed" | "rejected"
    created_at = Column(DateTime, default=datetime.utcnow)
