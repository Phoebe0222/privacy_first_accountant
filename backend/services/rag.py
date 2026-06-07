import httpx
import os
import chromadb
from pathlib import Path

CHROMA_PATH = os.getenv("CHROMA_PATH", str(Path(__file__).parent.parent.parent / "data" / "chroma_db"))
EMBED_MODEL = "nomic-embed-text"
OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
COLLECTION_NAME = "transactions"

_client = chromadb.PersistentClient(path=CHROMA_PATH)
_col = _client.get_or_create_collection(
    COLLECTION_NAME,
    metadata={"hnsw:space": "cosine"},
)


def _doc(t) -> str:
    return (
        f"Date: {t.date or 'unknown'}\n"
        f"Vendor: {t.vendor or 'unknown'}\n"
        f"Amount: ${t.amount:.2f}\n"
        f"Tax: ${t.tax:.2f}\n"
        f"Type: {t.type}\n"
        f"Category: {t.category}\n"
        f"Description: {t.description or ''}\n"
        f"Invoice: {t.invoice_number or ''}"
    )


async def _embed(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{OLLAMA_BASE}/api/embed",
            json={"model": EMBED_MODEL, "input": text},
        )
        return resp.json()["embeddings"][0]  # ← the vector



async def index_transaction(t) -> None:
    doc = _doc(t)
    embedding = await _embed(doc)
    _col.upsert(
        ids=[str(t.id)],
        embeddings=[embedding],
        documents=[doc],
        metadatas=[{
            "id": t.id,
            "type": t.type or "",
            "category": t.category or "",
            "date": t.date or "",
            "vendor": t.vendor or "",
            "amount": float(t.amount),
        }],
    )


def remove_transaction(transaction_id: int) -> None:
    try:
        _col.delete(ids=[str(transaction_id)])
    except Exception:
        pass

async def search(query: str, n_results: int = 15) -> list[str]:
    embedding = await _embed(query)       # ← embed the question
    results = _col.query(
        query_embeddings=[embedding],     # ← compare against all stored vectors
        n_results=min(n_results, _col.count()),  # ← return top 15 matches
    )
    return results["documents"][0]        # ← the matching transaction texts



async def reindex_all(transactions: list) -> int:
    for t in transactions:
        await index_transaction(t)
    return len(transactions)


def indexed_count() -> int:
    return _col.count()


_ato_col = _client.get_or_create_collection(
    "ato_rules",
    metadata={"hnsw:space": "cosine"},
)


async def search_ato_rules(query: str, year: str = "2025-2026", n_results: int = 5) -> list[dict]:
    """Search the ATO rules collection. Returns list of {text, category, url}."""
    if _ato_col.count() == 0:
        return []
    embedding = await _embed(query)
    where = {"year": year} if year else None
    results = _ato_col.query(
        query_embeddings=[embedding],
        n_results=min(n_results, _ato_col.count()),
        where=where,
    )
    out = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        out.append({"text": doc, "category": meta.get("category", ""), "url": meta.get("url", "")})
    return out
