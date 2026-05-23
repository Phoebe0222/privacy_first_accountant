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


def fetch_emails(
    host: str,
    port: int,
    username: str,
    password: str,
    days_back: int = 30,
) -> list[dict]:
    since = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
    results = []

    with IMAPClient(host, port=port, ssl=True, timeout=30) as client:
        client.login(username, password)
        client.select_folder("INBOX", readonly=True)
        uids = client.search(["SINCE", since])

        if not uids:
            return results

        # Step 1: fetch only headers for all emails (fast — no bodies/attachments)
        headers = client.fetch(uids, ["BODY[HEADER.FIELDS (SUBJECT FROM DATE)]"])
        financial_uids = []
        for uid, data in headers.items():
            raw_header = data[b"BODY[HEADER.FIELDS (SUBJECT FROM DATE)]"]
            msg = email.message_from_bytes(raw_header)
            subject = _decode_header_value(msg.get("Subject", ""))
            sender = _decode_header_value(msg.get("From", ""))
            if _is_financial(subject, ""):
                financial_uids.append((uid, subject, sender, msg.get("Date", "")))

        if not financial_uids:
            return results

        # Step 2: fetch full RFC822 only for emails that passed the subject filter
        full_uids = [uid for uid, *_ in financial_uids]
        messages = client.fetch(full_uids, ["RFC822"])
        uid_meta = {uid: (subject, sender, date) for uid, subject, sender, date in financial_uids}

        for uid, data in messages.items():
            raw = data[b"RFC822"]
            msg = email.message_from_bytes(raw)
            subject, sender, date = uid_meta.get(uid, ("", "", ""))
            body = _extract_text(msg)

            results.append({
                "uid": str(uid),
                "subject": subject,
                "from": sender,
                "date": date,
                "body": body,
                "raw_text": f"Subject: {subject}\nFrom: {sender}\nDate: {date}\n\n{body}",
                "attachments": _extract_attachments(msg),
            })

    return results
