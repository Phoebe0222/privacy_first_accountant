import logging
import httpx
import os
import chromadb
from pathlib import Path
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

CHROMA_PATH = os.getenv("CHROMA_PATH", str(Path(__file__).parent.parent.parent / "data" / "chroma_db"))
EMBED_MODEL = "nomic-embed-text"
OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
COLLECTION_NAME = "transactions"
ATO_RULES_DIR = Path(__file__).parent.parent / "data" / "ato_rules"

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


def _parse_seed_header(path: Path) -> tuple[str, str]:
    """Return (category, source_url) from a seed ATO rule file's header lines."""
    category = path.stem
    url = ""
    for line in path.read_text(encoding="utf-8").splitlines()[:5]:
        if line.startswith("Source:"):
            url = line.split(":", 1)[1].strip()
        elif line.startswith("Category:"):
            category = line.split(":", 1)[1].strip()
    return category, url


async def _fetch_page_text(url: str) -> str:
    """Fetch a live web page and return its visible text content."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                  headers={"User-Agent": "Mozilla/5.0"}) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup
    return main.get_text(separator="\n", strip=True)


async def _index_live_page(url: str, category: str, year: str) -> int:
    """Fetch a live ATO page, chunk it, embed each chunk, and upsert into the ato_rules collection."""
    from backend.services.ato_fetcher import _chunk
    text = await _fetch_page_text(url)
    chunks = _chunk(text)
    for i, chunk in enumerate(chunks):
        embedding = await _embed(chunk)
        _ato_col.upsert(
            ids=[f"ato_live_{year}_{category}_{i}"],
            embeddings=[embedding],
            documents=[chunk],
            metadatas=[{"year": year, "category": category, "url": url, "source": "live"}],
        )
    return len(chunks)


async def ensure_live_ato_rules(year: str = "2025-2026") -> int:
    """
    Live-fetch each seeded ATO page (backend/data/ato_rules/<year>/*.txt headers) from
    ato.gov.au and index it into the ato_rules collection. Idempotent per year — skips
    if live content has already been indexed for this year.
    """
    existing = _ato_col.get(where={"$and": [{"year": year}, {"source": "live"}]}, limit=1)
    if existing["ids"]:
        return 0

    rules_dir = ATO_RULES_DIR / year
    if not rules_dir.exists():
        return 0

    total = 0
    for path in sorted(rules_dir.glob("*.txt")):
        category, url = _parse_seed_header(path)
        if not url:
            continue
        try:
            total += await _index_live_page(url, category, year)
        except Exception as e:
            log.warning("Live ATO fetch failed for %s (%s): %s", category, url, e)
    return total


async def search_ato_rules(query: str, year: str = "2025-2026", n_results: int = 5) -> list[dict]:
    """Search the ATO rules collection. Live-fetches and indexes ATO pages on first use for `year`."""
    if year:
        await ensure_live_ato_rules(year)
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
