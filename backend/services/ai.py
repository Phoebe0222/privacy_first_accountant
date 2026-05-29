import os
import httpx

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
EXTRACT_MODEL = os.getenv("EXTRACT_MODEL", "llama3.2:3b")
VISION_MODEL = "moondream2"


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


CHAT_SYSTEM = """You are a private business accountant assistant. You have access to the user's financial data.
Answer questions about their transactions, spending, revenue, and cash flow.
Be concise and use numbers from the data provided. Format currency values clearly."""


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
