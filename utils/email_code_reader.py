'''Reads ICBC's verification-code email automatically via IMAP, so
auto-booking/rescheduling can complete with no human step. This is the
"auto-read from Gmail" path -- it replaces the Telegram-relay approval
step entirely, so nothing stops a booking short of CONFIG.py's settings
once a matching appointment is found. See CONFIG.py's comments.

Uses only the standard library (imaplib/email) -- no extra dependency.
'''

import email
import imaplib
import re
import time
from email.header import decode_header
from html import unescape
from typing import Optional

from CONFIG import VERIFICATION_EMAIL_ADDRESS, VERIFICATION_EMAIL_APP_PASSWORD

IMAP_SERVER = "imap.gmail.com"

# Raw HTML emails are full of incidental 6-digit strings that have
# nothing to do with the code -- CSS hex colors like #333333 above all
# (bit us once already: it matched before the real code did). So:
#   1. Strip <style>/<script> blocks and all tags before searching.
#   2. Prefer a match anchored near the words "verification code".
#   3. Exclude anything immediately preceded by "#" as a last-ditch guard
#      against a stray hex color slipping through.
_STYLE_OR_SCRIPT_RE = re.compile(r"<(style|script)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_CODE_NEAR_CONTEXT_RE = re.compile(r"verification code[^0-9]{0,60}(\d{6})", re.IGNORECASE)
_CODE_PATTERN = re.compile(r"(?<!#)\b(\d{6})\b")


def _connect() -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL(IMAP_SERVER)
    imap.login(VERIFICATION_EMAIL_ADDRESS, VERIFICATION_EMAIL_APP_PASSWORD)
    imap.select("INBOX")
    return imap


def get_latest_seen_uid() -> int:
    """Returns the highest message UID currently in the inbox. Call this
    right before triggering the code email, so an old code email already
    sitting in the inbox is never mistaken for the new one."""
    imap = _connect()
    try:
        status, data = imap.uid("search", None, "ALL")
        if status != "OK" or not data or not data[0]:
            return 0
        uids = [int(x) for x in data[0].split()]
        return max(uids) if uids else 0
    finally:
        imap.logout()


def _decode_subject(msg) -> str:
    parts = decode_header(msg.get("Subject", ""))
    return "".join(
        part.decode(encoding or "utf-8", errors="ignore") if isinstance(part, bytes) else part
        for part, encoding in parts
    )


def _html_to_text(html: str) -> str:
    html = _STYLE_OR_SCRIPT_RE.sub(" ", html)
    return unescape(_TAG_RE.sub(" ", html))


def _iter_text_candidates(msg):
    """Yields cleaned text from each text/plain or text/html part,
    plain-text first -- it's far less likely to contain incidental
    6-digit strings than raw HTML markup is."""
    parts = list(msg.walk()) if msg.is_multipart() else [msg]
    parts.sort(key=lambda p: 0 if p.get_content_type() == "text/plain" else 1)

    for part in parts:
        content_type = part.get_content_type()
        if content_type not in ("text/plain", "text/html"):
            continue
        try:
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            text = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
        except Exception:
            continue
        yield text if content_type == "text/plain" else _html_to_text(text)


def _extract_code(msg) -> Optional[str]:
    candidates = [_decode_subject(msg)] + list(_iter_text_candidates(msg))

    # First pass: a 6-digit number specifically near "verification code" --
    # the reliable signal.
    for text in candidates:
        match = _CODE_NEAR_CONTEXT_RE.search(text)
        if match:
            return match.group(1)

    # Fallback: any standalone 6-digit number, excluding hex colors.
    for text in candidates:
        match = _CODE_PATTERN.search(text)
        if match:
            return match.group(1)

    return None


def wait_for_code_email(since_uid: int, timeout_seconds: int, poll_interval: int = 5) -> Optional[str]:
    """Polls the inbox for a new message (UID greater than since_uid)
    that's from ICBC and contains a 6-digit verification code. Returns
    the code, or None on timeout.
    """
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        imap = _connect()
        try:
            status, data = imap.uid("search", None, f"UID {since_uid + 1}:*")
            uids = []
            if status == "OK" and data and data[0]:
                uids = sorted(int(x) for x in data[0].split() if int(x) > since_uid)

            for uid in uids:
                status, msg_data = imap.uid("fetch", str(uid), "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    continue
                msg = email.message_from_bytes(msg_data[0][1])

                if "icbc" not in msg.get("From", "").lower():
                    continue

                code = _extract_code(msg)
                if code:
                    return code
        finally:
            imap.logout()

        time.sleep(poll_interval)

    return None
