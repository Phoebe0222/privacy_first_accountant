import asyncio
import json
import os
import re
import httpx

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
EXTRACT_MODEL = "llama3.2:3b"
VISION_MODEL = "moondream2"

EXTRACTION_PROMPT = """Analyse the email text below and decide whether it contains a real financial transaction.

First, set "skip" to true if the email is ANY of the following — these are NOT financial transactions:
- Order dispatched / shipped / out for delivery / delivered / in transit
- Logistics or tracking update ("view logistics", "track your order", "tracking number", "your parcel is on its way")
- Marketing or promotional email with no actual charge
- Account notification with no dollar amount (password reset, login alert, newsletter)
- General correspondence with no invoice or payment

If "skip" is true, set all other fields to null and stop — do not guess amounts.

Otherwise set "skip" to false and extract the transaction details.

Rules for "type" — read carefully:
- "expense": YOU are paying money OUT. Strong signals: "you've paid", "you sent a payment", "receipt for your payment", "successfully sent a payment", "bill", "invoice", "amount due", "payment due", "please pay", "your bill has arrived", "order confirmation", "you placed an order"; you are the customer being charged.
- "income": money is flowing IN to you. Strong signals: "payment received from", "you've been paid", "funds deposited", "payout", "we've sent you", "money has been sent to you"; you are receiving funds FROM someone else.
- WARNING: "payment" alone does NOT mean income. "Receipt for your payment" and "you've paid [merchant]" are EXPENSES — you are the one who paid.
- A positive dollar amount does NOT mean income — receipts and invoices always show positive amounts.
- Utility bills, subscription charges, supplier invoices, and payment receipts where YOU paid are ALWAYS expenses.
- Subject "Receipt for Your Payment" is ALWAYS an expense.
- Default to "expense" when uncertain.

Return ONLY a valid JSON object — no explanation, no markdown, no extra text.

JSON format:
{{
  "skip": false,
  "date": "YYYY-MM-DD or null",
  "vendor": "company or person name",
  "amount": 0.00,
  "tax": 0.00,
  "category": "one of: food, transport, utilities, software, marketing, revenue, salary, office, subscription, other",
  "type": "expense or income — see rules above",
  "description": "one-line summary",
  "invoice_number": "string or null"
}}

Text:
{text}"""

CHAT_SYSTEM = """You are a private business accountant assistant. You have access to the user's financial data.
Answer questions about their transactions, spending, revenue, and cash flow.
Be concise and use numbers from the data provided. Format currency values clearly."""


def _parse_json(raw: str) -> dict:
    start = raw.find("{")
    if start == -1:
        raise ValueError(f"No JSON in model response: {raw[:200]}")
    depth, in_string, escape = 0, False, False
    for i, ch in enumerate(raw[start:], start):
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                snippet = raw[start : i + 1]
                snippet = re.sub(r"\bNone\b", "null", snippet)
                snippet = re.sub(r"\bTrue\b", "true", snippet)
                snippet = re.sub(r"\bFalse\b", "false", snippet)
                snippet = re.sub(r",\s*([}\]])", r"\1", snippet)  # trailing commas
                snippet = re.sub(r":\s*,", ": null,", snippet)    # missing values
                snippet = re.sub(r":\s*}", ": null}", snippet)     # missing last value
                return json.loads(snippet)
    raise ValueError(f"Incomplete JSON in model response: {raw[:200]}")


async def _ollama_generate(prompt: str, retries: int = 3) -> str:
    last_err = None
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{OLLAMA_BASE}/api/generate",
                    json={"model": EXTRACT_MODEL, "prompt": prompt, "stream": False},
                )
                if resp.status_code == 404:
                    # Model not loaded — pull it then retry
                    await client.post(
                        f"{OLLAMA_BASE}/api/pull",
                        json={"name": EXTRACT_MODEL, "stream": False},
                        timeout=300,
                    )
                    resp = await client.post(
                        f"{OLLAMA_BASE}/api/generate",
                        json={"model": EXTRACT_MODEL, "prompt": prompt, "stream": False},
                    )
                resp.raise_for_status()
                return resp.json()["response"]
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
    raise last_err


async def extract_transaction(text: str) -> dict:
    safe_text = text[:3000].replace("{", "{{").replace("}", "}}")
    prompt = EXTRACTION_PROMPT.format(text=safe_text)
    raw = await _ollama_generate(prompt)
    data = _parse_json(raw)
    data.setdefault("tax", 0.0)
    data.setdefault("invoice_number", None)
    return data


async def extract_from_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    import base64

    b64 = base64.b64encode(image_bytes).decode()
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{OLLAMA_BASE}/api/generate",
            json={
                "model": VISION_MODEL,
                "prompt": "Describe all text visible in this receipt or invoice image. Include vendor name, date, amounts, tax, and any invoice number.",
                "images": [b64],
                "stream": False,
            },
        )
        resp.raise_for_status()
        return resp.json()["response"]


async def chat(messages: list[dict], context: str) -> str:
    system = CHAT_SYSTEM + "\n\nCurrent financial data:\n" + context
    payload_messages = [{"role": "system", "content": system}] + messages

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{OLLAMA_BASE}/api/chat",
            json={"model": EXTRACT_MODEL, "messages": payload_messages, "stream": False},
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
