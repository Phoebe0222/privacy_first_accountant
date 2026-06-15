"""
Chat agent with tool calling for database read/write operations.

  ┌──────────────────────┐
  │  LLM + bound tools   │  decide: call a tool, or reply in plain text
  └──────────┬───────────┘
             │
             ├─ tool call ──► run it, append result as ToolMessage, repeat
             │   (search_transactions, update_transaction,
             │    bulk_update_category, get_financial_summary,
             │    query_tax_rules)
             │
             └─ plain-text reply
                  │
                  ▼
       ┌────────────────────┐
       │  Claim guard       │  claims an update was made, or lists
       └──────────┬─────────┘  "ID:n" rows, with no tool call this round?
                  │
                  ├─ yes ──► inject correction message, repeat
                  │
                  └─ no  ──► return reply to user

  Repeats up to 5 rounds total; if exhausted with no plain-text reply,
  returns "I wasn't able to complete that in time. Please try rephrasing.
  
Uses a separate CHAT_MODEL (default: qwen2.5:14b) — larger than EXTRACT_MODEL
so tool calling and instruction following are reliable.

The agent runs a loop: LLM decides which tool to call → tool executes → result
fed back → repeat until the LLM produces a plain text reply (max 5 rounds).
"""
import logging
import os
import re
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
async def update_transaction(
    transaction_id: int,
    category: Optional[str] = None,
    vendor: Optional[str] = None,
    tx_type: Optional[str] = None,
    date: Optional[str] = None,
    amount: Optional[float] = None,
) -> str:
    """
    Update fields of a single transaction by its ID. Only supply the fields you want to change.
    Updating category also clears the needs_review flag automatically.
    To update MULTIPLE transactions at once (e.g. "mark all these as subscription"),
    use bulk_update_category instead — do not call this tool in a loop.
    Returns a confirmation message or an error.
    """
    from backend.database import SessionLocal
    from backend.models import Transaction
    from backend.services import rag
    from backend.services.constants import VALID_CATEGORIES
    if category is not None and category not in VALID_CATEGORIES:
        return f"'{category}' is not a valid category. Valid categories: {', '.join(sorted(VALID_CATEGORIES))}"
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
        # Re-index so future categorisation can learn from this correction via history consensus.
        await rag.index_transaction(t)
        return f"Updated transaction {transaction_id}: {', '.join(changes)}."
    finally:
        db.close()


@tool
async def bulk_update_category(transaction_ids: list[int], category: str) -> str:
    """
    Set the category for multiple transactions at once, in a single call.
    Use this whenever the user wants the same change applied to several
    transactions (e.g. "mark all these Netflix charges as subscription").
    Clears the needs_review flag and sets category_confidence to 1.0 for each.
    Returns how many were updated and lists any IDs that were not found.
    """
    from backend.database import SessionLocal
    from backend.models import Transaction
    from backend.services import rag
    from backend.services.constants import VALID_CATEGORIES
    if category not in VALID_CATEGORIES:
        return f"'{category}' is not a valid category. Valid categories: {', '.join(sorted(VALID_CATEGORIES))}"
    db = SessionLocal()
    try:
        updated_ids = []
        not_found = []
        updated: list[Transaction] = []
        for tid in transaction_ids:
            t = db.get(Transaction, tid)
            if not t:
                not_found.append(tid)
                continue
            t.category = category
            t.needs_review = False
            t.category_confidence = 1.0
            updated_ids.append(tid)
            updated.append(t)
        db.commit()
        # Re-index so future categorisation can learn from this correction via history consensus.
        for t in updated:
            await rag.index_transaction(t)
        msg = f"Updated {len(updated_ids)} transaction(s) to category '{category}': {updated_ids}."
        if not_found:
            msg += f" Not found: {not_found}."
        return msg
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

_TOOLS = [search_transactions, update_transaction, bulk_update_category, get_financial_summary, query_tax_rules]
_TOOLS_BY_NAME = {t.name: t for t in _TOOLS}

# Matches a final reply that *claims* a transaction was changed (past tense /
# already-done framing). Used to catch the model fabricating a "done" summary
# without ever having called update_transaction/bulk_update_category.
_CLAIM_RE = re.compile(
    r"\bi(?:'ve| have)\s+(?:updated|changed|categori[sz]ed|re-?categori[sz]ed|marked)\b"
    r"|\b(?:have|has|are|is)\s+(?:been|now)\s+(?:updated|changed|categori[sz]ed|marked)\b"
    r"|\bsuccessfully\s+(?:updated|changed|categori[sz]ed)\b",
    re.IGNORECASE,
)

# Matches the "ID:<n>" format that search_transactions puts on each result row.
# Smaller models sometimes pattern-match this format from earlier tool output
# and invent new rows for a different query instead of calling the tool again.
_RESULT_CLAIM_RE = re.compile(r"\bID:\d+\b")

_SYSTEM = (
    "You are a private business accountant assistant for an Australian small business. "
    "You have tools to query and update the transaction database, and to look up ATO tax rules.\n\n"
    "Guidelines:\n"
    "- To answer questions about transactions, call search_transactions or get_financial_summary.\n"
    "- To answer questions about tax deductibility or ATO rules, call query_tax_rules.\n"
    "- To change a single transaction, first search to confirm it exists, then call update_transaction.\n"
    "- To change the category of MULTIPLE transactions, first search to collect their IDs, "
    "then call bulk_update_category ONCE with all the IDs. Never call update_transaction "
    "repeatedly in a loop for the same kind of change.\n"
    "- Never tell the user a transaction was changed unless a tool result confirms that exact "
    "ID was updated. If you ran out of tool calls before finishing, say so honestly instead "
    "of listing changes that didn't happen.\n"
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

    # Default Ollama num_ctx (2048) is too small once the 5 tool schemas, system
    # prompt, and 10 messages of chat history are all in the prompt — the model
    # silently loses the tool definitions and falls back to a plain-text guess.
    llm_with_tools = get_llm(model=CHAT_MODEL, num_ctx=8192).bind_tools(_TOOLS)

    made_write_change = False
    made_tool_call = False

    for _ in range(5):
        response = await llm_with_tools.ainvoke(lc_messages)
        lc_messages.append(response)

        if not response.tool_calls:
            content = response.content or ""
            if not made_write_change and _CLAIM_RE.search(content):
                log.warning("CHAT hallucinated update claim, nudging | %s", content[:200])
                lc_messages.append(HumanMessage(content=(
                    "You just claimed a transaction was changed, but you have not "
                    "successfully called update_transaction or bulk_update_category "
                    "in this conversation. Either call the correct tool now using the "
                    "IDs already found, or tell the user honestly that no change has "
                    "been made yet."
                )))
                continue
            if not made_tool_call and _RESULT_CLAIM_RE.search(content):
                log.warning("CHAT hallucinated search result, nudging | %s", content[:200])
                lc_messages.append(HumanMessage(content=(
                    "You listed transaction details, but you have not called "
                    "search_transactions or get_financial_summary in this conversation. "
                    "Call the appropriate tool now to get real data, then answer based "
                    "on its results."
                )))
                continue
            return content

        for tc in response.tool_calls:
            made_tool_call = True
            tool_fn = _TOOLS_BY_NAME.get(tc["name"])
            if tool_fn is None:
                result = f"Unknown tool: {tc['name']}"
            else:
                try:
                    result = await tool_fn.ainvoke(tc["args"])
                except Exception as e:
                    result = f"Tool error: {e}"
            if tc["name"] in ("update_transaction", "bulk_update_category") and str(result).startswith("Updated"):
                made_write_change = True
            log.info("CHAT TOOL | %s(%s) → %s", tc["name"], tc["args"], str(result)[:200])
            lc_messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

    return "I wasn't able to complete that in time. Please try rephrasing."
