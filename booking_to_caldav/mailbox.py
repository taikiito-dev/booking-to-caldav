"""Read-only IMAP source.

Opens the mailbox, fetches message bodies with BODY.PEEK so nothing is marked
as read, and never issues STORE, EXPUNGE, APPEND or MOVE. The account only
needs read access.
"""

from __future__ import annotations

import email
import email.policy
import imaplib
import re
import socket
import time
from datetime import date, datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message

from .parsers import Email

HTML_TAG = re.compile(r"<[^>]+>")


def _decoded_header(message: Message, name: str) -> str:
    raw = message.get(name, "")
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw


def _calendar_parts(message: Message) -> tuple[str, ...]:
    """Every text/calendar part, decoded.

    Some senders attach the invitation as application/ics instead of
    declaring text/calendar, so the filename is checked too.
    """
    found = []
    for part in message.walk():
        filename = (part.get_filename() or "").lower()
        if part.get_content_type() != "text/calendar" and not filename.endswith(
            ".ics"
        ):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            found.append(payload.decode(charset, errors="replace"))
        except LookupError:
            found.append(payload.decode("utf-8", errors="replace"))
    return tuple(found)


def _body_text(message: Message) -> str:
    """Prefer the text/plain alternative; fall back to de-tagged HTML."""
    plain: list[str] = []
    html: list[str] = []

    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_filename():
            continue  # skip attachments (the e-ticket PDF)
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        if part.get_content_subtype() == "plain":
            plain.append(text)
        elif part.get_content_subtype() == "html":
            html.append(text)

    if plain:
        return "\n".join(plain)
    stripped = HTML_TAG.sub("\n", "\n".join(html))
    return re.sub(r"\n{3,}", "\n\n", stripped)


def _received_date(message: Message, fallback: date) -> date:
    raw = message.get("Date")
    if not raw:
        return fallback
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return fallback
    return (parsed or datetime.now()).date()


class Mailbox:
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        folder: str = "INBOX",
        port: int = 993,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.folder = folder
        self._connection: imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> "Mailbox":
        self._connection = imaplib.IMAP4_SSL(self.host, self.port)
        self._connection.login(self.username, self.password)
        status, _ = self._connection.select(self.folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"cannot open folder {self.folder!r}")
        return self

    def __exit__(self, *_: object) -> None:
        if self._connection is None:
            return
        try:
            self._connection.close()
            self._connection.logout()
        except Exception:
            pass
        self._connection = None

    def recent(self, days: int = 30, limit: int = 200) -> list[Email]:
        if self._connection is None:
            raise RuntimeError("use Mailbox as a context manager")

        since = (date.today() - timedelta(days=days)).strftime("%d-%b-%Y")
        status, data = self._connection.search(None, "SINCE", since)
        if status != "OK":
            raise RuntimeError("IMAP search failed")

        ids = data[0].split()[-limit:]
        messages: list[Email] = []
        for message_id in ids:
            status, payload = self._connection.fetch(message_id, "(BODY.PEEK[])")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            message = email.message_from_bytes(
                payload[0][1], policy=email.policy.default
            )
            messages.append(
                Email(
                    subject=_decoded_header(message, "Subject"),
                    sender=_decoded_header(message, "From"),
                    body=_body_text(message),
                    received=_received_date(message, date.today()),
                    calendars=_calendar_parts(message),
                )
            )
        return messages

    @property
    def supports_idle(self) -> bool:
        if self._connection is None:
            return False
        return "IDLE" in getattr(self._connection, "capabilities", ())

    def wait_for_mail(self, timeout: int = 540) -> bool:
        """Block until the server announces new mail, or until timeout.

        Uses IMAP IDLE (RFC 2177): the connection stays open and the server
        pushes an untagged EXISTS when something arrives, so there is no
        polling. IDLE is re-issued by the caller well inside the 29 minute
        limit the RFC sets. Returns True if mail arrived.

        Falls back to sleeping when the server does not advertise IDLE.
        """
        connection = self._connection
        if connection is None:
            raise RuntimeError("use Mailbox as a context manager")
        if not self.supports_idle:
            time.sleep(timeout)
            return True  # let the caller re-scan; it is cheap and idempotent

        tag = connection._new_tag()
        connection.send(b"%s IDLE\r\n" % tag)
        if not connection.readline().startswith(b"+"):
            raise RuntimeError("server refused IDLE")

        stream = connection.socket()
        previous_timeout = stream.gettimeout()
        arrived = False
        try:
            stream.settimeout(timeout)
            while True:
                line = connection.readline()
                if not line:
                    break
                if b"EXISTS" in line or b"RECENT" in line:
                    arrived = True
                    break
        except (socket.timeout, TimeoutError, OSError):
            pass
        finally:
            try:
                stream.settimeout(previous_timeout)
                connection.send(b"DONE\r\n")
                connection._command_complete("IDLE", tag)
            except Exception:
                pass
        return arrived
