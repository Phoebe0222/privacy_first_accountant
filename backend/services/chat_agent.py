"""
Chat agent with tool calling for database read/write operations.

Uses a separate CHAT_MODEL (default: qwen2.5:14b) — larger than EXTRACT_MODEL
so tool calling and instruction following are reliable.

The agent runs a loop: LLM decides which tool to call → tool executes → result
fed back → repeat until the LLM produces a plain text reply (max 5 rounds).
"""
import logging
import os
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from backend.services.utils import get_llm

log = logging.getLogger(__name__)

CHAT_MODEL = os.getenv("CHAT_MODEL", "qwen2.5:14b")


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def search_transactions(
    vendor: Optional[str] = None,
    category: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    tx_type: Optional[str] = None,
    needs_review: Optional[bool] = None,
    limit: int = 20,
) -> str:
    """
    Search transactions from the database. All filters are optional.
    tx_type must be 'income' or 'expense'.
    category must be one of: food, grocery, drink, transport, travel, utilities,
    software, marketing, fee, gym, medical, office, subscription, shopping,
    leisure, material, other, sales, revenue, salary, refund.
    Returns matching transactions with their IDs, dates, vendors, amounts, categories, and types.
    """
    from backend.database import SessionLocal
    from backend.models import Transaction
    db = SessionLocal()
    try:
        q = db.query(Transaction)
        if vendor:
            q = q.filter(Transaction.vendor.ilike(f"%{vendor}%"))
        if category:
            q = q.filter(Transaction.category == category)
        if date_from:
            q = q.filter(Transaction.date >= date_from)
        if date_to:
            q = q.filter(Transaction.date <= date_to)
        if tx_type:
            q = q.filter(Transaction.type == tx_type)
        if needs_review is not None:
            q = q.filter(Transaction.needs_review == needs_review)
        items = q.order_by(Transaction.date.desc()).limit(limit).all()
        if not items:
            return "No transactions found."
        lines = [
            f"ID:{t.id}  {t.date}  {t.vendor}  ${t.amount:.2f}  [{t.category}]  ({t.type})"
            for t in items
        ]
        return f"Found {len(items)} transaction(s):\n" + "\n".join(lines)
    finally:
        db.close()


@tool
def update_transaction(
    transaction_id: int,
    category: Optional[str] = None,
    vendor: Optional[str] = None,
    tx_type: Optional[str] = None,
    date: Optional[str] = None,
    amount: Optional[float] = None,
) -> str:
    """
    Update fields of a transaction by its ID. Only supply the fields you want to change.
    Updating category also clears the needs_review flag automatically.
    Returns a confirmation message or an error.
    """
    from backend.database import SessionLocal
    from backend.models import Transaction
    db = SessionLocal()
    try:
        t = db.get(Transaction, transaction_id)
        if not t:
            return f"Transaction {transaction_id} not found."
        changes = []
        if category is not None:
            t.category = category
            t.needs_review = False
            t.category_confidence = 1.0
            changes.append(f"category → {category}")
        if vendor is not None:
            t.vendor = vendor
            changes.append(f"vendor → {vendor}")
        if tx_type is not None:
            t.type = tx_type
            changes.append(f"type → {tx_type}")
        if date is not None:
            t.date = date
            changes.append(f"date → {date}")
        if amount is not None:
            t.amount = amount
            changes.append(f"amount → ${amount:.2f}")
        if not changes:
            return "No changes specified."
        db.commit()
        return f"Updated transaction {transaction_id}: {', '.join(changes)}."
    finally:
        db.close()


@tool
def get_financial_summary(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> str:
    """
    Get income and expense totals and a breakdown by category.
    Dates must be in YYYY-MM-DD format. Omit both for all-time totals.
    """
    from backend.database import SessionLocal
    from backend.models import Transaction
    db = SessionLocal()
    try:
        q = db.query(Transaction)
        if date_from:
            q = q.filter(Transaction.date >= date_from)
        if date_to:
            q = q.filter(Transaction.date <= date_to)
        items = q.all()
        if not items:
            return "No transactions found for this period."
        income = sum(t.amount for t in items if t.type == "income")
        expenses = sum(t.amount for t in items if t.type == "expense")
        by_cat: dict[str, float] = {}
        for t in items:
            if t.type == "expense":
                key = t.category or "other"
                by_cat[key] = by_cat.get(key, 0) + t.amount
        cat_lines = "\n".join(
            f"  {cat}: ${amt:.2f}"
            for cat, amt in sorted(by_cat.items(), key=lambda x: x[1], reverse=True)
        )
        return (
            f"Income:   ${income:,.2f}\n"
            f"Expenses: ${expenses:,.2f}\n"
            f"Net:      ${income - expenses:,.2f}\n\n"
            f"Expenses by category:\n{cat_lines}"
        )
    finally:
        db.close()


@tool
async def query_tax_rules(question: str, year: str = "2025-2026") -> str:
    """
    Search Australian ATO tax rules to answer questions about deductibility.
    Use this when the user asks whether something is tax deductible, what records
    they need to keep, or how a deduction works under Australian tax law.
    question: a plain-English question, e.g. "Is home office rent deductible?"
    year: tax year, default 2025-2026.
    Returns relevant ATO guidance with source URLs.
    """
    from backend.services import rag
    results = await rag.search_ato_rules(question, year=year)
    if not results:
        return "No ATO rules indexed yet. Run the ato-init container first."
    lines = []
    seen_urls: set[str] = set()
    for r in results:
        lines.append(r["text"])
        if r["url"] and r["url"] not in seen_urls:
            lines.append(f"Source: {r['url']}")
            seen_urls.add(r["url"])
        lines.append("")
    return "\n".join(lines).strip()


# ── Agent ─────────────────────────────────────────────────────────────────────

_TOOLS = [search_transactions, update_transaction, get_financial_summary, query_tax_rules]
_TOOLS_BY_NAME = {t.name: t for t in _TOOLS}

_SYSTEM = (
    "You are a private business accountant assistant for an Australian small business. "
    "You have tools to query and update the transaction database, and to look up ATO tax rules.\n\n"
    "Guidelines:\n"
    "- To answer questions about transactions, call search_transactions or get_financial_summary.\n"
    "- To answer questions about tax deductibility or ATO rules, call query_tax_rules.\n"
    "- To change a transaction, first search to confirm it exists, then call update_transaction.\n"
    "- Always confirm what was changed or found. Be concise. Format amounts as $X.XX AUD.\n"
    "- When citing ATO rules, include the source URL."
)


async def chat(messages: list[dict], system_context: str = "") -> str:
    """
    Run the tool-calling chat agent.
    messages: list of {role: 'user'|'assistant', content: str}
    system_context: optional extra text appended to the system prompt (e.g. ATO rules)
    """
    system = _SYSTEM + (f"\n\n{system_context}" if system_context else "")
    lc_messages = [SystemMessage(content=system)]
    for m in messages:
        if m["role"] == "user":
            lc_messages.append(HumanMessage(content=m["content"]))
        elif m["role"] == "assistant":
            lc_messages.append(AIMessage(content=m["content"]))

    llm_with_tools = get_llm(model=CHAT_MODEL).bind_tools(_TOOLS)

    for _ in range(5):
        response = await llm_with_tools.ainvoke(lc_messages)
        lc_messages.append(response)

        if not response.tool_calls:
            return response.content

        for tc in response.tool_calls:
            tool_fn = _TOOLS_BY_NAME.get(tc["name"])
            if tool_fn is None:
                result = f"Unknown tool: {tc['name']}"
            else:
                try:
                    result = await tool_fn.ainvoke(tc["args"])
                except Exception as e:
                    result = f"Tool error: {e}"
            log.info("CHAT TOOL | %s(%s) → %s", tc["name"], tc["args"], str(result)[:200])
            lc_messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

    return "I wasn't able to complete that in time. Please try rephrasing."
