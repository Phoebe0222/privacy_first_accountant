from datetime import datetime
from sqlalchemy import Boolean, Column, Integer, String, Float, Text, DateTime
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
    created_at = Column(DateTime, default=datetime.utcnow)
