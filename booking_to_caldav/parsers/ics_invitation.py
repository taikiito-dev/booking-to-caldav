"""Calendar invitations attached to an email.

An invitation already contains the thing every other parser has to work to
reconstruct: the start, the end, and the timezone, stated unambiguously. So
this parser does not read the prose at all, and it works for any sender that
attaches one — a dental clinic, a restaurant platform, a meeting request.

Deliberately not handled:

- METHOD:CANCEL and METHOD:REPLY. Removing an event the user may have edited
  is a bigger decision than adding one, and a reply is somebody else's answer
  to an invitation, not a booking.
- Recurrence (RRULE). The first occurrence is written and the repeat is
  dropped rather than guessed at, with a note in the description.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..core import LOCAL, Event
from . import Email, Parser, register

UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
DURATION = re.compile(
    r"^P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$"
)


def unfold(text: str) -> list[str]:
    """RFC 5545 continuation lines begin with a space or tab."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def split_property(line: str) -> tuple[str, dict[str, str], str]:
    """`DTSTART;TZID=Asia/Tokyo:20260811T100000` -> name, params, value."""
    head, _, value = line.partition(":")
    pieces = head.split(";")
    name = pieces[0].upper()
    params = {}
    for piece in pieces[1:]:
        key, _, raw = piece.partition("=")
        params[key.upper()] = raw.strip('"')
    return name, params, value


def unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def default_timezone() -> ZoneInfo:
    """For invitations that state a wall-clock time with no zone at all."""
    name = os.environ.get("DEFAULT_TIMEZONE", "UTC")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def parse_moment(value: str, params: dict[str, str]):
    """Return (datetime, all_day). Naive only when all_day."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value[:8], "%Y%m%d"), True
    if value.endswith("Z"):
        return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(
            tzinfo=timezone.utc
        ), False
    naive = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    tzid = params.get("TZID")
    if tzid:
        try:
            return naive.replace(tzinfo=ZoneInfo(tzid)), False
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return naive.replace(tzinfo=default_timezone()), False


def parse_duration(value: str) -> timedelta | None:
    found = DURATION.match(value.strip().lstrip("+"))
    if not found:
        return None
    weeks, days, hours, minutes, seconds = (int(x or 0) for x in found.groups())
    return timedelta(
        weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds
    )


class IcsInvitation(Parser):
    name = "Calendar invitation attached to the email (.ics)"

    def matches(self, email: Email) -> bool:
        return bool(email.calendars)

    def parse(self, email: Email) -> list[Event]:
        events: list[Event] = []
        for payload in email.calendars:
            events.extend(self._read(payload, email))
        return events

    def _read(self, payload: str, email: Email) -> list[Event]:
        lines = unfold(payload)

        method = ""
        for line in lines:
            name, _, value = split_property(line)
            if name == "METHOD":
                method = value.strip().upper()
                break
        if method in ("CANCEL", "REPLY", "DECLINECOUNTER"):
            return []

        events: list[Event] = []
        current: dict | None = None
        for line in lines:
            name, params, value = split_property(line)
            if name == "BEGIN" and value.strip().upper() == "VEVENT":
                current = {}
                continue
            if name == "END" and value.strip().upper() == "VEVENT":
                if current is not None:
                    built = self._build(current, email)
                    if built:
                        events.append(built)
                current = None
                continue
            if current is None:
                continue
            if name in ("DTSTART", "DTEND", "DURATION", "SUMMARY", "LOCATION",
                        "DESCRIPTION", "UID", "STATUS", "RRULE", "ORGANIZER"):
                current[name] = (params, value)
        return events

    def _build(self, fields: dict, email: Email) -> Event | None:
        if "DTSTART" not in fields:
            return None
        if fields.get("STATUS", ({}, ""))[1].strip().upper() == "CANCELLED":
            return None

        start, all_day = parse_moment(*reversed(fields["DTSTART"]))

        if "DTEND" in fields:
            end, _ = parse_moment(*reversed(fields["DTEND"]))
        elif "DURATION" in fields:
            span = parse_duration(fields["DURATION"][1]) or timedelta(hours=1)
            end = start + span
        else:
            end = start + (timedelta(days=1) if all_day else timedelta(hours=1))

        summary = unescape(fields.get("SUMMARY", ({}, ""))[1]).strip()
        if not summary:
            summary = email.subject.strip() or "Booking"

        details = []
        description = unescape(fields.get("DESCRIPTION", ({}, ""))[1]).strip()
        if description:
            details.append(description)
        if "RRULE" in fields:
            details.append(
                "This invitation repeats. Only the first occurrence was imported."
            )
        details.append(f"From the invitation attached to: {email.subject}")
        details.append(f"Imported by booking-to-caldav from: {self.name}")

        return Event(
            uid=self._uid(fields, start),
            summary=summary,
            start=start,
            end=end,
            category=LOCAL,
            location=unescape(fields.get("LOCATION", ({}, ""))[1]).strip() or None,
            details=tuple(details),
            label=f"{summary[:40]} {self._when(start, all_day)}",
            all_day=all_day,
        )

    @staticmethod
    def _when(start: datetime, all_day: bool) -> str:
        return f"{start:%Y-%m-%d}" if all_day else f"{start:%Y-%m-%d %H:%M %Z}"

    @staticmethod
    def _uid(fields: dict, start: datetime) -> str:
        """Namespaced, never the invitation's own UID.

        Reusing the original would overwrite the copy a mail client created
        when the invitation was accepted — replacing a complete event,
        attendees and all, with this reconstruction of it.
        """
        original = fields.get("UID", ({}, ""))[1].strip()
        seed = original or f"{fields.get('SUMMARY')}|{start.isoformat()}"
        digest = hashlib.sha1(seed.encode()).hexdigest()[:10]
        stem = UNSAFE.sub("-", original.split("@")[0])[:40].strip("-").lower()
        return f"{stem or 'invitation'}-{digest}-ics@booking-to-caldav"


register(IcsInvitation())
