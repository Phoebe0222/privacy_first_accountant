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
    """Import a receipt/marketplace CSV (PayPal, Stripe, Etsy, etc.)."""
    return await _start_csv_job(file, source="csv")


@router.post("/bank-csv")
async def upload_bank_csv(file: UploadFile = File(...)):
    """Import a bank statement CSV (ANZ, CommBank, Westpac, etc.)."""
    return await _start_csv_job(file, source="bank_csv")


async def _start_csv_job(file: UploadFile, source: str):
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
    asyncio.create_task(_run_csv(job_id, headers, rows, filename, source=source))
    return {"job_id": job_id, "status": "running"}


async def _run_csv(job_id: str, headers: list, rows: list, filename: str, source: str = "csv"):
    try:
        mapping = await map_csv_columns(headers, rows[:5])
        log.info("CSV MAPPING | %s", mapping)
        transactions = apply_mapping(rows, mapping)
        log.info("CSV APPLY | rows=%d  transactions=%d", len(rows), len(transactions))
        if not transactions:
            _jobs[job_id] = {"status": "failed", "error": "No valid transactions found in file."}
            return

        # Normalise vendor names — use both vendor column and description column.
        # Bank CSVs often have the real merchant in the description
        # (e.g. "PAYPAL *AIAUMARKETS 4029357733 AUS" while vendor says "PayPal").
        from backend.services.vendor_normalizer import normalize_vendor, _PROCESSOR_PREFIX_RE

        # Vendor column values that are payment processors, not real merchants
        _GENERIC_PROCESSORS = frozenset({"paypal", "stripe", "square", "eftpos", "afterpay", "payme", "unknown"})

        to_normalise: set[str] = set()
        for tx in transactions:
            if tx.get("type") in ("transfer-in", "transfer-out"):
                continue
            if tx["vendor"] not in ("Unknown", ""):
                to_normalise.add(tx["vendor"])
            desc = tx.get("description", "")
            if desc and desc != tx["vendor"]:
                to_normalise.add(desc)

        norm_cache: dict[str, str] = {}
        for raw in to_normalise:
            norm_cache[raw] = await normalize_vendor(raw)

        for tx in transactions:
            if tx.get("type") in ("transfer-in", "transfer-out"):
                continue
            raw_vendor = tx["vendor"]
            raw_desc = tx.get("description", "")

            vendor_norm = norm_cache.get(raw_vendor, raw_vendor)
            desc_norm = norm_cache.get(raw_desc, raw_desc) if raw_desc and raw_desc != raw_vendor else None

            # Prefer description-derived vendor when vendor column is a known processor or generic
            use_desc = bool(
                desc_norm
                and desc_norm not in ("Unknown", "Internal Transfer")
                and (
                    raw_vendor in ("Unknown", "")
                    or raw_vendor.lower().strip() in _GENERIC_PROCESSORS
                    or bool(_PROCESSOR_PREFIX_RE.match(raw_vendor))
                )
            )

            tx["vendor"] = desc_norm if use_desc else vendor_norm
            if tx.get("description") == raw_vendor:
                tx["description"] = tx["vendor"]

        db = SessionLocal()
        try:
            category_rules = _load_category_rules(db)

            # Deduplicate vendors that need categorisation.
            # Transfers (transfer-in / transfer-out) are typed by regex — skip LLM categorisation.
            pending: dict[str, tuple[str, str, float, str, str]] = {}
            for tx in transactions:
                if tx.get("type") in ("transfer-in", "transfer-out"):
                    continue
                key = tx["vendor"] if tx["vendor"] != "Unknown" else tx.get("description", "Unknown")
                if key not in pending:
                    pending[key] = (
                        tx["vendor"],
                        tx.get("description", ""),
                        float(tx.get("amount") or 0),
                        tx.get("type", "expense"),
                        tx.get("category", ""),
                    )

            # Categorise all unique keys concurrently
            sem = asyncio.Semaphore(5)

            async def _categorize_key(key: str, vendor: str, desc: str, amount: float, tx_type: str, bank_category: str):
                async with sem:
                    return key, await categorize_transaction(vendor, desc, amount, tx_type, category_rules, bank_category)

            results = await asyncio.gather(
                *[asyncio.create_task(_categorize_key(k, v, d, a, t, b)) for k, (v, d, a, t, b) in pending.items()],
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

            # Build a dedup set from transactions already imported from THIS SAME FILE.
            # Scoping to source_ref means:
            #   - True same-file duplicates are still blocked
            #   - Deleted transactions from this file come back when re-importing
            #   - Cross-file overlap (different filenames, same date range) is not blocked
            # Key: (date, amount) — excludes type so user edits don't bypass dedup.
            existing_keys: set[tuple] = {
                (t.date, round(t.amount, 2))
                for t in db.query(Transaction.date, Transaction.amount)
                    .filter(Transaction.source == source, Transaction.source_ref == filename)
                    .all()
            }

            # Build a vendor → business flag map from ALL existing transactions.
            # This preserves user-set business flags across delete+reimport cycles:
            # if the user marked "Bupa Australia" as business, new imports of the same
            # vendor inherit that flag even after clearing the file.
            vendor_business: dict[str, bool] = {
                t.vendor: t.business
                for t in db.query(Transaction.vendor, Transaction.business)
                    .filter(Transaction.business == True)  # noqa: E712
                    .all()
                if t.vendor
            }

            added = 0
            duplicates = 0
            for tx in transactions:
                tx_key = (tx.get("date"), round(float(tx.get("amount") or 0), 2))
                if tx_key in existing_keys:
                    duplicates += 1
                    continue

                key = tx["vendor"] if tx["vendor"] != "Unknown" else tx.get("description", "Unknown")
                cat = pipeline_results.get(key, {"category": "other", "confidence": 0.0, "needs_review": True, "tax_kind": "na"})
                data = {**tx, "category": cat["category"],
                        "needs_review": cat["needs_review"],
                        "category_confidence": cat["confidence"],
                        "tax_kind": cat.get("tax_kind", "na"),
                        "business": cat.get("tax_kind", "na") == "business"}

                # Inherit user-set tax_kind from any prior transaction with this vendor
                if tx.get("vendor") in vendor_business:
                    data = {**data, "tax_kind": "business", "business": True}

                t = _build_transaction(data, source=source, source_ref=filename, raw_text="")
                db.add(t)
                added += 1
                existing_keys.add(tx_key)  # also prevents intra-file duplicates
            db.commit()
            log.info("CSV SAVE | added=%d  duplicates_skipped=%d", added, duplicates)
            transaction_ids = [
                t.id for t in db.query(Transaction).filter(Transaction.source_ref == filename).all()
            ]
        finally:
            db.close()

        _jobs[job_id] = {"status": "done", "added": added, "skipped": len(rows) - added - duplicates, "duplicates": duplicates}
        asyncio.create_task(_index_transactions(transaction_ids))
    except Exception as e:
        _jobs[job_id] = {"status": "failed", "error": str(e)}
