"""Unwrap an email that is really somebody else's email.

Half the bookings in a household are not made by the person running this. The
confirmation lands in a spouse's mailbox and arrives here as a forward, so the
sender is a person and the subject starts with "Fwd:". Every parser matches on
the sender, which means a forward matches nothing at all.

Rather than teach each parser about forwarding, this strips one layer off:
find the quoted header block, read the original sender, subject and date out
of it, and hand the parsers an Email that looks like the one that would have
arrived directly.

Only one layer is stripped per attempt, and the registry retries, so a forward
of a forward resolves by repetition rather than by recursion here.
"""

from __future__ import annotations

import email.utils
import re
from datetime import date

from . import Email

# Gmail and most webmail; Apple Mail; Outlook (English and Japanese).
MARKERS = (
    re.compile(r"-{2,}\s*Forwarded message\s*-{2,}", re.I),
    re.compile(r"Begin forwarded message\s*:", re.I),
    re.compile(r"-{2,}\s*Original Message\s*-{2,}", re.I),
    re.compile(r"^\s*転送されたメッセージ\s*:?", re.M),
)

FIELD = re.compile(
    r"^\s*(?:From|Subject|Date|To|Sent|差出人|件名|日付|送信日時|宛先)\s*:",
    re.I | re.M,
)

SUBJECT_PREFIX = re.compile(r"^\s*(?:(?:Fwd|FW|Fw|Re)\s*:|転送\s*:)\s*", re.I)


def _field(block: str, *names: str) -> str | None:
    for name in names:
        found = re.search(
            rf"^\s*{name}\s*:\s*(.+)$", block, re.I | re.M
        )
        if found and found.group(1).strip():
            return found.group(1).strip()
    return None


def _address(value: str) -> str:
    """"Trip.com" <JP_HTL_NoReply@trip.com>  ->  JP_HTL_NoReply@trip.com"""
    _, addr = email.utils.parseaddr(value)
    return addr or value


def _original_date(block: str, fallback: date) -> date:
    """The forward's own Date header is days or weeks later than the booking.

    Year inference leans on the received date, so the original one is worth
    recovering: "Oct 11, 2026 8:02 AM" as written by the forwarding client is
    not an RFC 2822 date, hence the second attempt.
    """
    raw = _field(block, "Date", "Sent", "日付", "送信日時")
    if not raw:
        return fallback
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
        if parsed:
            return parsed.date()
    except (TypeError, ValueError):
        pass
    loose = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2}),?\s+(\d{4})", raw)
    if loose:
        from ..core import MONTHS

        month = MONTHS.get(loose.group(1).title())
        if month:
            try:
                return date(int(loose.group(3)), month, int(loose.group(2)))
            except ValueError:
                pass
    return fallback


def unwrap(message: Email) -> Email | None:
    """Return the quoted original, or None if this is not a forward."""
    for marker in MARKERS:
        found = marker.search(message.body)
        if found:
            break
    else:
        return None

    rest = message.body[found.end() :]

    # The header block runs until a line that is not a header. Allow blank and
    # continuation lines inside it, since clients wrap long subjects.
    lines = rest.splitlines(keepends=True)
    cut = 0
    consumed = 0
    for index, line in enumerate(lines):
        if FIELD.match(line):
            cut = index + 1
        elif line.strip() and not line.startswith((" ", "\t", ">")):
            break
        consumed = index + 1
    if not cut:
        return None
    header_block = "".join(lines[:cut])
    body = "".join(lines[max(cut, consumed) :])

    sender = _field(header_block, "From", "差出人")
    subject = _field(header_block, "Subject", "件名")
    if not sender:
        return None

    return Email(
        subject=SUBJECT_PREFIX.sub("", subject or message.subject),
        sender=_address(sender),
        body=body,
        received=_original_date(header_block, message.received),
        calendars=message.calendars,
    )
