import json
import os
import re
import httpx

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
EXTRACT_MODEL = "llama3.2:3b"
VISION_MODEL = "moondream2"

EXTRACTION_PROMPT = """Extract financial transaction details from the text below.
Return ONLY a valid JSON object — no explanation, no markdown, no extra text.
Use null for any field you cannot determine.

JSON format:
{{
  "date": "YYYY-MM-DD or null",
  "vendor": "company or person name",
  "amount": 0.00,
  "tax": 0.00,
  "category": "one of: food, transport, utilities, software, marketing, revenue, salary, office, subscription, other",
  "type": "income or expense",
  "description": "one-line summary",
  "invoice_number": "string or null"
}}

Text:
{text}"""

CHAT_SYSTEM = """You are a private business accountant assistant. You have access to the user's financial data.
Answer questions about their transactions, spending, revenue, and cash flow.
Be concise and use numbers from the data provided. Format currency values clearly."""


async def extract_transaction(text: str) -> dict:
    prompt = EXTRACTION_PROMPT.format(text=text[:4000])
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{OLLAMA_BASE}/api/generate",
            json={"model": EXTRACT_MODEL, "prompt": prompt, "stream": False},
        )
        resp.raise_for_status()
        raw = resp.json()["response"]

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in model response: {raw[:200]}")

    data = json.loads(match.group())
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
