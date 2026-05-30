import asyncio
import logging
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.database import SessionLocal
from backend.models import Transaction
from backend.services.csv_mapping_agent import map_csv_columns
from backend.services.csv_ingestion import parse_csv, apply_mapping
from backend.services.categorization_agent import categorize_transaction
from backend.routers._import_helpers import (
    _jobs, _load_category_rules, _to_float, _build_transaction, _index_transactions,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/import", tags=["import"])


@router.post("/csv")
async def upload_csv(file: UploadFile = File(...)):
    file_bytes = await file.read()
    filename = file.filename or "upload.csv"

    try:
        headers, rows = parse_csv(file_bytes, filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")
    if not headers:
        raise HTTPException(status_code=400, detail="File has no headers.")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running"}
    asyncio.create_task(_run_csv(job_id, headers, rows, filename))
    return {"job_id": job_id, "status": "running"}


async def _run_csv(job_id: str, headers: list, rows: list, filename: str):
    try:
        mapping = await map_csv_columns(headers, rows[:5])
        log.info("CSV MAPPING | %s", mapping)
        transactions = apply_mapping(rows, mapping)
        log.info("CSV APPLY | rows=%d  transactions=%d", len(rows), len(transactions))
        if not transactions:
            _jobs[job_id] = {"status": "failed", "error": "No valid transactions found in file."}
            return

        # Normalise vendor names (deduplicated — each unique raw name resolved once)
        from backend.services.vendor_normalizer import normalize_vendor
        vendor_map: dict[str, str] = {}
        for raw_vendor in {tx["vendor"] for tx in transactions if tx["vendor"] != "Unknown"}:
            vendor_map[raw_vendor] = await normalize_vendor(raw_vendor)
        for tx in transactions:
            raw = tx["vendor"]
            tx["vendor"] = vendor_map.get(raw, raw)
            if tx.get("description") == raw:
                tx["description"] = tx["vendor"]

        db = SessionLocal()
        try:
            category_rules = _load_category_rules(db)

            # Deduplicate vendors that need categorisation
            pending: dict[str, tuple[str, str, float, str]] = {}
            for tx in transactions:
                csv_category = tx.get("category") or ""
                if csv_category and csv_category != "other":
                    continue
                key = tx["vendor"] if tx["vendor"] != "Unknown" else tx.get("description", "Unknown")
                if key not in pending:
                    pending[key] = (
                        tx["vendor"],
                        tx.get("description", ""),
                        float(tx.get("amount") or 0),
                        tx.get("type", "expense"),
                    )

            # Categorise all unique keys concurrently
            sem = asyncio.Semaphore(5)

            async def _categorize_key(key: str, vendor: str, desc: str, amount: float, tx_type: str):
                async with sem:
                    return key, await categorize_transaction(vendor, desc, amount, tx_type, category_rules)

            results = await asyncio.gather(
                *[asyncio.create_task(_categorize_key(k, v, d, a, t)) for k, (v, d, a, t) in pending.items()],
                return_exceptions=True,
            )
            pipeline_results: dict[str, dict] = {}
            for r in results:
                if isinstance(r, Exception):
                    log.warning("CSV categorise error: %s", r)
                    continue
                key, cat_result = r
                pipeline_results[key] = cat_result
                log.info("CSV CAT | %s → %s (%.0f%%) method=%s",
                         key, cat_result["category"], cat_result["confidence"] * 100, cat_result["method"])

            added = 0
            for tx in transactions:
                csv_category = tx.get("category") or ""
                if csv_category and csv_category != "other":
                    data = {**tx, "needs_review": False, "category_confidence": 1.0}
                else:
                    key = tx["vendor"] if tx["vendor"] != "Unknown" else tx.get("description", "Unknown")
                    cat = pipeline_results.get(key, {"category": "other", "confidence": 0.0, "needs_review": True})
                    data = {**tx, "category": cat["category"],
                            "needs_review": cat["needs_review"],
                            "category_confidence": cat["confidence"]}
                t = _build_transaction(data, source="csv", source_ref=filename, raw_text="")
                db.add(t)
                added += 1
            db.commit()
            transaction_ids = [
                t.id for t in db.query(Transaction).filter(Transaction.source_ref == filename).all()
            ]
        finally:
            db.close()

        _jobs[job_id] = {"status": "done", "added": added, "skipped": len(rows) - added}
        asyncio.create_task(_index_transactions(transaction_ids))
    except Exception as e:
        _jobs[job_id] = {"status": "failed", "error": str(e)}
