"""
Index ATO deduction rules into ChromaDB from bundled local text files.
Run as a one-off init job:
  python -m backend.services.ato_fetcher --year 2025-2026

Files live at: backend/data/ato_rules/<year>/*.txt
Each file has a header block:
  Source: <url>
  Category: <name>
  Tax Year: <year>

Idempotent — skips if the year is already loaded.
"""
import argparse
import logging
import os
import sys
import time
from pathlib import Path

import httpx
import chromadb

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
log = logging.getLogger(__name__)

CHROMA_PATH = os.getenv("CHROMA_PATH", str(Path(__file__).parent.parent.parent / "data" / "chroma_db"))
OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
EMBED_MODEL  = "nomic-embed-text"
COLLECTION   = "ato_rules"
CHUNK_SIZE   = 600
CHUNK_OVERLAP = 80

RULES_DIR = Path(__file__).parent.parent / "data" / "ato_rules"


def _parse_file(path: Path) -> tuple[str, str, str]:
    """Return (category, source_url, body_text) from a rule file."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    category = path.stem
    url = ""
    body_start = 0
    for i, line in enumerate(lines):
        if line.startswith("Source:"):
            url = line.split(":", 1)[1].strip()
        elif line.startswith("Category:"):
            category = line.split(":", 1)[1].strip()
        elif line.strip() == "" and i < 5:
            body_start = i + 1
    body = "\n".join(lines[body_start:]).strip()
    return category, url, body


def _chunk(text: str) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunks.append(text[start:end])
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return [c for c in chunks if len(c.strip()) > 50]


def _embed(text: str) -> list[float]:
    resp = httpx.post(
        f"{OLLAMA_BASE}/api/embed",
        json={"model": EMBED_MODEL, "input": text},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


def _wait_for_ollama(retries: int = 12, delay: int = 10):
    for i in range(retries):
        try:
            httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=5)
            log.info("Ollama is ready")
            return
        except Exception:
            log.info("Waiting for Ollama… (%d/%d)", i + 1, retries)
            time.sleep(delay)
    log.error("Ollama did not become ready — aborting")
    sys.exit(1)


def main(year: str):
    rules_path = RULES_DIR / year
    if not rules_path.exists():
        log.error("No rules directory found at %s", rules_path)
        sys.exit(1)

    rule_files = sorted(rules_path.glob("*.txt"))
    if not rule_files:
        log.error("No .txt rule files found in %s", rules_path)
        sys.exit(1)

    _wait_for_ollama()

    client = chromadb.PersistentClient(path=CHROMA_PATH)
    col = client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})

    # Idempotency check
    existing = col.get(where={"year": year}, limit=1)
    if existing["ids"]:
        log.info("ATO rules for %s already indexed (%d docs total) — skipping", year, col.count())
        return

    log.info("Indexing %d ATO rule files for %s", len(rule_files), year)

    total_chunks = 0
    for path in rule_files:
        category, url, body = _parse_file(path)
        chunks = _chunk(body)
        log.info("  %-20s → %d chunks  (%s)", category, len(chunks), path.name)

        for i, chunk in enumerate(chunks):
            try:
                embedding = _embed(chunk)
            except Exception as e:
                log.warning("  Embed failed for %s chunk %d: %s", category, i, e)
                continue

            col.upsert(
                ids=[f"ato_{year}_{category}_{i}"],
                embeddings=[embedding],
                documents=[chunk],
                metadatas=[{"year": year, "category": category, "url": url, "chunk_index": i}],
            )
            total_chunks += 1

    log.info("Done — indexed %d chunks for %s", total_chunks, year)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", default="2025-2026")
    args = parser.parse_args()
    main(args.year)
