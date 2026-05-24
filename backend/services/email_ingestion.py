import email
import re
from datetime import datetime, timedelta
from email.header import decode_header

from bs4 import BeautifulSoup
from imapclient import IMAPClient


FINANCIAL_KEYWORDS = [
    "invoice", "receipt", "payment", "order", "transaction", "charge",
    "subscription", "billing", "statement", "purchase", "refund", "deposit",
]


def _decode_header_value(value: str) -> str:
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _extract_text(msg: email.message.Message) -> str:
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain" and not plain:
                plain = part.get_payload(decode=True).decode("utf-8", errors="replace")
            elif ct == "text/html" and not html:
                html = part.get_payload(decode=True).decode("utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            if msg.get_content_type() == "text/html":
                html = payload.decode("utf-8", errors="replace")
            else:
                plain = payload.decode("utf-8", errors="replace")

    if plain:
        return plain[:6000]
    if html:
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator=" ", strip=True)[:6000]
    return ""


ATTACHMENT_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp"}
ATTACHMENT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def _extract_attachments(msg: email.message.Message) -> list[dict]:
    attachments = []
    for part in msg.walk():
        disposition = part.get("Content-Disposition", "")
        if "attachment" not in disposition and "inline" not in disposition:
            continue
        mime_type = part.get_content_type()
        filename = part.get_filename() or ""
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if mime_type not in ATTACHMENT_MIME_TYPES and ext not in ATTACHMENT_EXTENSIONS:
            continue
        payload = part.get_payload(decode=True)
        if payload:
            attachments.append({"filename": filename, "mime_type": mime_type, "bytes": payload})
    return attachments


def _is_financial(subject: str, body: str) -> bool:
    combined = (subject + " " + body[:500]).lower()
    return any(kw in combined for kw in FINANCIAL_KEYWORDS)


def fetch_email_headers(
    host: str,
    port: int,
    username: str,
    password: str,
    days_back: int = 30,
) -> list[dict]:
    """Return lightweight header dicts {uid, subject, from, date} for all emails in range."""
    since = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
    results = []
    with IMAPClient(host, port=port, ssl=True, timeout=30) as client:
        client.login(username, password)
        client.select_folder("INBOX", readonly=True)
        uids = client.search(["SINCE", since])
        if not uids:
            return results
        raw_headers = client.fetch(uids, ["BODY[HEADER.FIELDS (SUBJECT FROM DATE)]"])
        for uid, data in raw_headers.items():
            msg = email.message_from_bytes(data[b"BODY[HEADER.FIELDS (SUBJECT FROM DATE)]"])
            results.append({
                "uid": str(uid),
                "subject": _decode_header_value(msg.get("Subject", "")),
                "from": _decode_header_value(msg.get("From", "")),
                "date": msg.get("Date", ""),
            })
    return results


def fetch_email_bodies(
    host: str,
    port: int,
    username: str,
    password: str,
    headers: list[dict],
) -> list[dict]:
    """Fetch full RFC822 bodies for the given header dicts and return complete email dicts."""
    if not headers:
        return []
    uid_meta = {h["uid"]: h for h in headers}
    int_uids = [int(uid) for uid in uid_meta]
    results = []
    with IMAPClient(host, port=port, ssl=True, timeout=30) as client:
        client.login(username, password)
        client.select_folder("INBOX", readonly=True)
        messages = client.fetch(int_uids, ["RFC822"])
        for uid, data in messages.items():
            msg = email.message_from_bytes(data[b"RFC822"])
            meta = uid_meta[str(uid)]
            body = _extract_text(msg)
            results.append({
                **meta,
                "body": body,
                "raw_text": f"Subject: {meta['subject']}\nFrom: {meta['from']}\nDate: {meta['date']}\n\n{body}",
                "attachments": _extract_attachments(msg),
            })
    return results
