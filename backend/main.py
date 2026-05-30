import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database import init_db
from backend.routers import transactions, chat
from backend.routers._import_helpers import router as import_jobs_router
from backend.routers.email_import import router as email_import_router
from backend.routers.file_import import router as file_import_router
from backend.routers.csv_import import router as csv_import_router
from backend.routers.rag_router import router as rag_router
from backend.routers.vendor_rules import router as vendor_rules_router
from backend.routers.ato_rules import router as ato_rules_router

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s",
)

app = FastAPI(title="Private Accountant API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(transactions.router)
app.include_router(import_jobs_router)
app.include_router(email_import_router)
app.include_router(file_import_router)
app.include_router(csv_import_router)
app.include_router(chat.router)
app.include_router(rag_router)
app.include_router(vendor_rules_router)
app.include_router(ato_rules_router)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}
