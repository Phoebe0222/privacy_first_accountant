import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.services.extraction_agent import extract_from_image, extract_from_text, extract_payslip_fields
from backend.services.file_ingestion import extract_text_from_pdf, is_image_file, is_pdf_file, normalise_image
from backend.routers._import_helpers import (
    _jobs, _to_float, _build_transaction, _index_transactions,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/import", tags=["import"])


@router.post("/file")
async def upload_file(file: UploadFile = File(...)):
    filename = file.filename or ""
    file_bytes = await file.read()

    if not is_pdf_file(filename) and not is_image_file(filename):
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload a PDF or image.")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running"}
    asyncio.create_task(_run_file_extraction(job_id, file_bytes, filename))
    return {"job_id": job_id, "status": "running"}


@router.post("/payslip")
async def upload_payslip(file: UploadFile = File(...)):
    filename = file.filename or ""
    file_bytes = await file.read()
    if not is_pdf_file(filename) and not is_image_file(filename):
        raise HTTPException(status_code=400, detail="Unsupported file type. Upload a PDF or image.")
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running"}
    asyncio.create_task(_run_payslip_extraction(job_id, file_bytes, filename))
    return {"job_id": job_id, "status": "running"}


async def _run_payslip_extraction(job_id: str, file_bytes: bytes, filename: str):
    from backend.database import SessionLocal
    from backend.models import AppSettings
    try:
        if is_pdf_file(filename):
            raw_text = extract_text_from_pdf(file_bytes)
        else:
            raw_text = await extract_from_image(normalise_image(file_bytes))

        if not raw_text.strip():
            _jobs[job_id] = {"status": "failed", "error": "Could not extract text from payslip."}
            return

        data = await extract_payslip_fields(raw_text)

        if data["gross_salary_ytd"] <= 0 and data["payg_withheld_ytd"] <= 0:
            _jobs[job_id] = {"status": "failed", "error": "Could not extract salary figures from payslip."}
            return

        db = SessionLocal()
        try:
            def _set(key: str, value: str) -> None:
                row = db.get(AppSettings, key)
                if row:
                    row.value = value
                else:
                    db.add(AppSettings(key=key, value=value))

            if data["gross_salary_ytd"] > 0:
                _set("gross_salary", str(data["gross_salary_ytd"]))
            if data["payg_withheld_ytd"] > 0:
                _set("payg_withheld", str(data["payg_withheld_ytd"]))
            db.commit()
        finally:
            db.close()

        _jobs[job_id] = {"status": "done", "added": 0, "skipped": 0, "payslip": data}
    except Exception as e:
        _jobs[job_id] = {"status": "failed", "error": str(e)}


async def _run_file_extraction(job_id: str, file_bytes: bytes, filename: str):
    from backend.database import SessionLocal
    try:
        if is_pdf_file(filename):
            raw_text = extract_text_from_pdf(file_bytes)
            source = "pdf"
        else:
            raw_text = await extract_from_image(normalise_image(file_bytes))
            source = "image"

        if not raw_text.strip():
            _jobs[job_id] = {"status": "failed", "error": "Could not extract text from file."}
            return

        log.info("AI extracting | %s", filename)
        t = time.monotonic()
        data = await extract_from_text(raw_text)
        log.info("AI done %.1fs | skip=%s vendor=%s amount=%s category=%s | %s",
                 time.monotonic() - t, data.get("skip"), data.get("vendor"),
                 data.get("amount"), data.get("category"), filename)
        if not _to_float(data.get("amount")):
            _jobs[job_id] = {"status": "failed", "error": "Could not extract a non-zero amount from file."}
            return

        db = SessionLocal()
        try:
            t = _build_transaction(data, source=source, source_ref=filename, raw_text=raw_text)
            db.add(t)
            db.commit()
            db.refresh(t)
            transaction = {
                "id": t.id, "date": t.date, "vendor": t.vendor,
                "amount": t.amount, "tax": t.tax, "category": t.category, "type": t.type,
            }
        finally:
            db.close()

        asyncio.create_task(_index_transactions([transaction["id"]]))
        _jobs[job_id] = {"status": "done", "added": 1, "skipped": 0, "transaction": transaction}
    except Exception as e:
        _jobs[job_id] = {"status": "failed", "error": str(e)}
