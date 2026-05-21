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

        messages = client.fetch(uids, ["RFC822", "ENVELOPE"])
        for uid, data in messages.items():
            raw = data[b"RFC822"]
            msg = email.message_from_bytes(raw)
            subject = _decode_header_value(msg.get("Subject", ""))
            body = _extract_text(msg)

            if not _is_financial(subject, body):
                continue

            results.append(
                {
                    "uid": str(uid),
                    "subject": subject,
                    "from": _decode_header_value(msg.get("From", "")),
                    "date": msg.get("Date", ""),
                    "body": body,
                    "raw_text": f"Subject: {subject}\nFrom: {msg.get('From','')}\nDate: {msg.get('Date','')}\n\n{body}",
                }
            )

    return results
