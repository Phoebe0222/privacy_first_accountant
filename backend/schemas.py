from typing import Optional

from pydantic import BaseModel


class EmailAccountCreate(BaseModel):
    name: str
    email: str
    imap_host: str
    imap_port: int = 993
    username: str
    password: str


class VendorRuleCreate(BaseModel):
    vendor_pattern: str
    category: str


class ATORuleCreate(BaseModel):
    title: str
    description: str


class ChatRequest(BaseModel):
    message: str


class TransactionCreate(BaseModel):
    date: str
    vendor: str
    amount: float
    tax: float = 0.0
    category: str
    type: str
    source: str = "manual"
    description: Optional[str] = None
    invoice_number: Optional[str] = None


class TransactionUpdate(BaseModel):
    date: Optional[str] = None
    vendor: Optional[str] = None
    amount: Optional[float] = None
    tax: Optional[float] = None
    category: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    invoice_number: Optional[str] = None
    needs_review: Optional[bool] = None
