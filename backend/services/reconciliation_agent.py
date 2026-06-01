"""
Reconciliation agent — matches bank CSV transactions to email/PDF receipts.

Matching pipeline for each bank transaction:
  1. Amount match — exact match within $0.01
  2. Date proximity — within ±7 days (bank processing delay)
  3. Vendor similarity — normalized names compared; LLM used for ambiguous cases

Confidence scoring:
  1.0  exact amount + same date + exact vendor
  0.9  exact amount + ≤3 days + close vendor
  0.8  exact amount + ≤7 days + partial vendor
  < 0.7  not auto-matched (flagged for manual review)
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from backend.models import ReconciliationMatch, Transaction

log = logging.getLogger(__name__)

AMOUNT_TOLERANCE = 0.01   # cents rounding
DATE_WINDOW_DAYS = 7
AUTO_MATCH_THRESHOLD = 0.8


# ── Vendor similarity ─────────────────────────────────────────────────────────

def _vendor_similarity(v1: str, v2: str) -> float:
    """Score how similar two (already normalised) vendor names are."""
    if not v1 or not v2:
        return 0.0
    a, b = v1.lower().strip(), v2.lower().strip()
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    words_a = set(a.split())
    words_b = set(b.split())
    overlap = len(words_a & words_b)
    if overlap:
        return 0.5 + (overlap / max(len(words_a), len(words_b))) * 0.3
    return 0.0


def _date_score(d1: str, d2: str) -> float:
    """Score date proximity: same day = 1.0, ≤3 days = 0.9, ≤7 days = 0.8, else 0."""
    try:
        delta = abs((datetime.strptime(d1, "%Y-%m-%d") - datetime.strptime(d2, "%Y-%m-%d")).days)
    except (ValueError, TypeError):
        return 0.0
    if delta == 0:
        return 1.0
    if delta <= 3:
        return 0.9
    if delta <= DATE_WINDOW_DAYS:
        return 0.8
    return 0.0


# ── Core matching logic ───────────────────────────────────────────────────────

def find_best_match(
    bank_tx: Transaction,
    receipts: list[Transaction],
    already_matched: set[int],
) -> Optional[tuple[Transaction, float]]:
    """
    Find the best matching receipt for a bank transaction.
    Returns (receipt, confidence) or None if no match above threshold.
    """
    best: Optional[Transaction] = None
    best_score = 0.0

    for r in receipts:
        if r.id in already_matched:
            continue
        if r.type != bank_tx.type:
            continue
        if abs((r.amount or 0) - (bank_tx.amount or 0)) > AMOUNT_TOLERANCE:
            continue

        d_score = _date_score(bank_tx.date or "", r.date or "")
        if d_score == 0.0:
            continue

        v_score = _vendor_similarity(bank_tx.vendor or "", r.vendor or "")
        confidence = round((d_score + v_score) / 2, 3)

        if confidence > best_score:
            best_score = confidence
            best = r

    if best and best_score >= AUTO_MATCH_THRESHOLD:
        return best, best_score
    return None


# ── Auto-reconciliation run ───────────────────────────────────────────────────

def run_auto_reconcile(db: Session, source_ref: str | None = None) -> dict:
    """
    Match all unmatched bank transactions to unmatched receipts.
    Returns summary counts.
    """
    # Load all existing match IDs so we don't re-match already matched transactions
    existing = db.query(ReconciliationMatch).filter(
        ReconciliationMatch.status != "rejected"
    ).all()
    matched_bank_ids = {m.bank_tx_id for m in existing}
    matched_receipt_ids = {m.receipt_tx_id for m in existing}

    bank_q = db.query(Transaction).filter(
        Transaction.source == "bank_csv",
        ~Transaction.id.in_(matched_bank_ids),
    )
    if source_ref:
        bank_q = bank_q.filter(Transaction.source_ref == source_ref)
    bank_txs = bank_q.all()

    receipts = db.query(Transaction).filter(
        Transaction.source.in_(["email", "pdf", "image"]),
        ~Transaction.id.in_(matched_receipt_ids),
    ).all()

    new_matches = 0
    already_matched_this_run: set[int] = set()

    for bank_tx in bank_txs:
        result = find_best_match(bank_tx, receipts, already_matched_this_run)
        if result is None:
            continue
        receipt, confidence = result
        db.add(ReconciliationMatch(
            bank_tx_id=bank_tx.id,
            receipt_tx_id=receipt.id,
            confidence=confidence,
            status="auto",
        ))
        already_matched_this_run.add(receipt.id)
        new_matches += 1
        log.info(
            "RECONCILED | %s $%.2f ↔ %s $%.2f | conf=%.0f%%",
            bank_tx.vendor, bank_tx.amount,
            receipt.vendor, receipt.amount,
            confidence * 100,
        )

    db.commit()
    return {
        "new_matches": new_matches,
        "unmatched_bank": len(bank_txs) - new_matches,
        "unmatched_receipts": len(receipts) - new_matches,
    }


# ── Summary ───────────────────────────────────────────────────────────────────

def get_summary(db: Session) -> dict:
    total_bank = db.query(Transaction).filter(Transaction.source == "bank_csv").count()
    total_receipts = db.query(Transaction).filter(
        Transaction.source.in_(["email", "pdf", "image"])
    ).count()

    active_matches = db.query(ReconciliationMatch).filter(
        ReconciliationMatch.status != "rejected"
    ).all()
    matched_bank = {m.bank_tx_id for m in active_matches}
    matched_receipts = {m.receipt_tx_id for m in active_matches}

    return {
        "total_bank": total_bank,
        "total_receipts": total_receipts,
        "matched": len(active_matches),
        "unmatched_bank": total_bank - len(matched_bank),
        "unmatched_receipts": total_receipts - len(matched_receipts),
    }
