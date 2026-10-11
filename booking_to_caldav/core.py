"""Shared types: a flight segment, airport timezones, year inference, iCalendar output."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

PRODID = "-//booking-to-caldav//EN"


class UnknownAirport(KeyError):
    """Raised when an IATA code has no timezone mapping."""


class UnknownStayLocation(KeyError):
    """Raised when a hotel address gives away no timezone."""


# Airline confirmation emails print local clock times with no timezone, so the
# IATA code is the only way back to an absolute instant. Add rows as needed.
AIRPORT_TZ: dict[str, str] = {
    # Southeast Asia
    "SIN": "Asia/Singapore",
    "KUL": "Asia/Kuala_Lumpur",
    "BKK": "Asia/Bangkok",
    "DMK": "Asia/Bangkok",
    "CGK": "Asia/Jakarta",
    "DPS": "Asia/Makassar",
    "MNL": "Asia/Manila",
    "SGN": "Asia/Ho_Chi_Minh",
    "HAN": "Asia/Ho_Chi_Minh",
    # East Asia
    "HND": "Asia/Tokyo",
    "NRT": "Asia/Tokyo",
    "KIX": "Asia/Tokyo",
    "ITM": "Asia/Tokyo",
    "NGO": "Asia/Tokyo",
    "FUK": "Asia/Tokyo",
    "CTS": "Asia/Tokyo",
    "OKA": "Asia/Tokyo",
    "HKG": "Asia/Hong_Kong",
    "TPE": "Asia/Taipei",
    "ICN": "Asia/Seoul",
    "PVG": "Asia/Shanghai",
    "SHA": "Asia/Shanghai",
    "PEK": "Asia/Shanghai",
    "PKX": "Asia/Shanghai",
    "CAN": "Asia/Shanghai",
    "CTU": "Asia/Shanghai",
    "TFU": "Asia/Shanghai",
    # South Asia / Middle East
    "DEL": "Asia/Kolkata",
    "BOM": "Asia/Kolkata",
    "BLR": "Asia/Kolkata",
    "DXB": "Asia/Dubai",
    "DOH": "Asia/Qatar",
    "AUH": "Asia/Dubai",
    # Europe
    "LHR": "Europe/London",
    "LGW": "Europe/London",
    "CDG": "Europe/Paris",
    "FRA": "Europe/Berlin",
    "MUC": "Europe/Berlin",
    "AMS": "Europe/Amsterdam",
    "ZRH": "Europe/Zurich",
    "BCN": "Europe/Madrid",
    "MAD": "Europe/Madrid",
    "MXP": "Europe/Rome",
    "FCO": "Europe/Rome",
    "IST": "Europe/Istanbul",
    "CPH": "Europe/Copenhagen",
    # Oceania
    "SYD": "Australia/Sydney",
    "MEL": "Australia/Melbourne",
    "BNE": "Australia/Brisbane",
    "PER": "Australia/Perth",
    "AKL": "Pacific/Auckland",
    # Americas
    "JFK": "America/New_York",
    "EWR": "America/New_York",
    "LAX": "America/Los_Angeles",
    "SFO": "America/Los_Angeles",
    "SEA": "America/Los_Angeles",
    "ORD": "America/Chicago",
    "IAH": "America/Chicago",
    "DFW": "America/Chicago",
    "YVR": "America/Vancouver",
    "YYZ": "America/Toronto",
    "GRU": "America/Sao_Paulo",
    "HNL": "Pacific/Honolulu",
    # Africa
    "JNB": "Africa/Johannesburg",
    "CPT": "Africa/Johannesburg",
    "CAI": "Africa/Cairo",
    "NBO": "Africa/Nairobi",
}

# A hotel confirmation has no IATA code. It prints an address and says the
# times are "hotel local time", which is true and useless. The address is the
# only handle, so these are substrings looked for in it, longest first. A hotel
# whose address matches nothing raises rather than guessing: a stay written to
# the wrong hour is worse than a stay that was not written.
STAY_TZ_HINTS: tuple[tuple[str, str], ...] = (
    ("〒", "Asia/Tokyo"),          # the Japanese postal mark
    ("日本", "Asia/Tokyo"),
    ("Japan", "Asia/Tokyo"),
    ("シンガポール", "Asia/Singapore"),
    ("Singapore", "Asia/Singapore"),
    ("台湾", "Asia/Taipei"),
    ("Taiwan", "Asia/Taipei"),
    ("香港", "Asia/Hong_Kong"),
    ("Hong Kong", "Asia/Hong_Kong"),
    ("韓国", "Asia/Seoul"),
    ("Korea", "Asia/Seoul"),
    ("タイ", "Asia/Bangkok"),
    ("Thailand", "Asia/Bangkok"),
    ("Malaysia", "Asia/Kuala_Lumpur"),
    ("Indonesia", "Asia/Jakarta"),
    ("Spain", "Europe/Madrid"),
    ("スペイン", "Europe/Madrid"),
)

STAY_MARK_START_HOUR = 19
STAY_MARK_END_HOUR = 21
"""A stay is written as one short evening block per night, not as one long
block from check-in to check-out.

The literal truth — 15:00 on the 6th until 12:00 on the 7th — is a 21-hour bar
that covers two days and hides everything else on them. What the calendar is
actually being asked is "where are we sleeping on the 6th", and one evening
block per night answers that at a glance, the same way the nights already
entered by hand do. The real check-in and check-out times go in the
description, where they are read once, at the desk.
"""

WEEKDAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}

MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def airport_tz(iata: str) -> ZoneInfo:
    code = iata.strip().upper()
    try:
        return ZoneInfo(AIRPORT_TZ[code])
    except KeyError as exc:
        raise UnknownAirport(
            f"no timezone known for airport {code!r}; add it to AIRPORT_TZ"
        ) from exc


def stay_tz(address: str) -> ZoneInfo:
    for hint, zone in STAY_TZ_HINTS:
        if hint.lower() in address.lower():
            return ZoneInfo(zone)
    raise UnknownStayLocation(
        f"no timezone known for address {address!r}; add a hint to STAY_TZ_HINTS"
    )


def resolve_year(
    day: int,
    month: int,
    weekday: str | None,
    received: date,
    horizon_years: int = 2,
) -> int:
    """Pick the year for a day/month that the email never stated.

    Airline emails print "24 Dec (Wed)" with no year. Two signals narrow it:
    the weekday the email itself printed, and the fact that a booking
    confirmation describes a flight in the future. A small backward slack
    absorbs same-day confirmations across timezones.
    """
    candidates = [received.year + offset for offset in range(horizon_years + 1)]
    matches = []
    for year in candidates:
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue  # e.g. 29 Feb in a non-leap year
        if (candidate - received).days < -2:
            continue
        if weekday and candidate.weekday() != WEEKDAYS[weekday[:3].title()]:
            continue
        matches.append(candidate)
    if not matches:
        raise ValueError(
            f"cannot resolve a year for {day:02d}/{month:02d} "
            f"(weekday={weekday!r}, received={received.isoformat()})"
        )
    return matches[0].year


TRAVEL = "travel"
"""Takes you away from home: flights, trains, hotels.

Worth a household calendar someone else can see.
"""

LOCAL = "local"
"""Happens where you live: a barber, a dentist, a restaurant booking.

Nobody else needs it, so it belongs on a private calendar. Parsers declare
which kind of thing they found and the destination follows from that, rather
than every event landing in one place.
"""


@dataclass(frozen=True)
class Segment:
    """One flight leg, as printed in a confirmation email."""

    carrier: str          # "SQ"
    number: str           # "634"
    origin: str           # "SIN"
    destination: str      # "HND"
    depart_local: datetime  # naive, clock time at origin
    arrive_local: datetime  # naive, clock time at destination
    booking_ref: str
    cabin: str | None = None
    aircraft: str | None = None
    origin_terminal: str | None = None
    destination_terminal: str | None = None
    source: str = ""      # parser name, for the event description
    category: str = TRAVEL  # which calendar this belongs on

    @property
    def flight(self) -> str:
        return f"{self.carrier}{self.number}"

    @property
    def depart_utc(self) -> datetime:
        return self.depart_local.replace(tzinfo=airport_tz(self.origin)).astimezone(
            timezone.utc
        )

    @property
    def arrive_utc(self) -> datetime:
        return self.arrive_local.replace(
            tzinfo=airport_tz(self.destination)
        ).astimezone(timezone.utc)

    @property
    def uid(self) -> str:
        """Stable across re-runs, so a repeated import updates instead of duplicating."""
        seed = f"{self.booking_ref}|{self.flight}|{self.depart_local.isoformat()}"
        digest = hashlib.sha1(seed.encode()).hexdigest()[:10]
        return f"{self.booking_ref.lower()}-{self.flight.lower()}-{digest}@booking-to-caldav"

    def to_event(self) -> "Event":
        return _segment_to_event(self)


@dataclass(frozen=True)
class Event:
    """What actually gets written. Parsers produce these, directly or via a
    richer type of their own, so the writer never needs to know whether it is
    looking at a flight or a dentist."""

    uid: str
    summary: str
    start: datetime          # timezone-aware, or naive date when all_day
    end: datetime
    category: str = LOCAL
    location: str | None = None
    details: tuple[str, ...] = ()
    label: str = ""          # one line for the log
    all_day: bool = False

    def to_event(self) -> "Event":
        return self


@dataclass(frozen=True)
class Stay:
    """One hotel booking, which may cover several nights.

    Unlike a flight this is not one event: `events()` returns one per night.
    A parser returns the Stay and lets it decide, so the shape of a night is
    defined once rather than in every hotel parser.
    """

    hotel: str
    address: str
    check_in: date
    check_out: date
    booking_ref: str
    check_in_time: str | None = None   # as printed, e.g. "15:00"
    check_out_time: str | None = None  # as printed, e.g. "12:00"
    guest: str | None = None
    room: str | None = None
    meals: str | None = None
    price: str | None = None
    cancellation: str | None = None
    phone: str | None = None
    confirmation: str | None = None    # the hotel's own number, not the agent's
    source: str = ""
    category: str = TRAVEL

    @property
    def nights(self) -> int:
        return max((self.check_out - self.check_in).days, 1)

    def uid(self, night: date) -> str:
        seed = f"{self.booking_ref}|{self.hotel}|{night.isoformat()}"
        digest = hashlib.sha1(seed.encode()).hexdigest()[:10]
        return (
            f"{self.booking_ref.lower()}-{night:%Y%m%d}-stay-{digest}"
            "@booking-to-caldav"
        )

    def _details(self) -> tuple[str, ...]:
        stated = []
        if self.check_in_time or self.check_out_time:
            stated.append(
                f"Check-in {self.check_in:%Y-%m-%d} {self.check_in_time or '?'} / "
                f"check-out {self.check_out:%Y-%m-%d} {self.check_out_time or '?'} "
                "(hotel local time)"
            )
        for label, value in (
            ("Guest", self.guest),
            ("Room", self.room),
            ("Meals", self.meals),
            ("Price", self.price),
            ("Cancellation", self.cancellation),
            ("Phone", self.phone),
            ("Hotel confirmation", self.confirmation),
        ):
            if value:
                stated.append(f"{label}: {value}")
        stated.append(f"Booking reference: {self.booking_ref}")
        if self.address:
            stated.append(f"Address: {self.address}")
        if self.source:
            stated.append(f"Imported by booking-to-caldav from: {self.source}")
        return tuple(stated)

    def events(self) -> list[Event]:
        zone = stay_tz(self.address)
        details = self._details()
        nights = []
        for offset in range(self.nights):
            night = date.fromordinal(self.check_in.toordinal() + offset)
            start = datetime(
                night.year, night.month, night.day, STAY_MARK_START_HOUR, tzinfo=zone
            )
            end = datetime(
                night.year, night.month, night.day, STAY_MARK_END_HOUR, tzinfo=zone
            )
            suffix = ""
            if self.nights > 1:
                suffix = f" ({offset + 1}/{self.nights})"
            nights.append(
                Event(
                    uid=self.uid(night),
                    summary=f"Stay at {self.hotel}{suffix}",
                    start=start,
                    end=end,
                    category=self.category,
                    location=self.address or self.hotel,
                    details=details,
                    label=(
                        f"stay {self.hotel} {night:%Y-%m-%d} "
                        f"({self.booking_ref})"
                    ),
                )
            )
        return nights


def _segment_to_event(segment: "Segment") -> Event:
    details = [f"Booking reference: {segment.booking_ref}"]
    if segment.cabin:
        details.append(f"Cabin: {segment.cabin}")
    if segment.aircraft:
        details.append(f"Aircraft: {segment.aircraft}")
    if segment.origin_terminal:
        details.append(f"Departs {segment.origin} terminal {segment.origin_terminal}")
    if segment.destination_terminal:
        details.append(
            f"Arrives {segment.destination} terminal {segment.destination_terminal}"
        )
    details.append(
        f"Local times: {segment.depart_local:%Y-%m-%d %H:%M} {segment.origin} "
        f"→ {segment.arrive_local:%Y-%m-%d %H:%M} {segment.destination}"
    )
    if segment.source:
        details.append(f"Imported by booking-to-caldav from: {segment.source}")

    return Event(
        uid=segment.uid,
        summary=f"{segment.flight} {segment.origin} → {segment.destination}",
        start=segment.depart_utc,
        end=segment.arrive_utc,
        category=segment.category,
        location=segment.origin,
        details=tuple(details),
        label=(
            f"{segment.flight} {segment.origin}->{segment.destination} "
            f"{segment.depart_local:%Y-%m-%d %H:%M} ({segment.booking_ref})"
        ),
    )


def _ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """RFC 5545 octet-aware folding at 75 octets.

    Backing off a continuation byte (10xxxxxx) is not enough on its own: when
    the cut lands immediately after a lead byte, that byte is not a
    continuation byte, so nothing moves and a character is split in half. The
    cut has to retreat to a true character boundary, which is any byte that is
    not a continuation byte and that begins a sequence short enough to fit.
    """
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    chunks, start = [], 0
    limit = 75
    while start < len(raw):
        end = min(start + limit, len(raw))
        if end < len(raw):
            while end > start and not _starts_character(raw, end):
                end -= 1
            if end == start:  # one character is wider than the budget
                end = min(start + limit, len(raw))
                while end < len(raw) and not _starts_character(raw, end):
                    end += 1
        chunks.append(raw[start:end].decode("utf-8"))
        start = end
        limit = 74  # continuation lines carry a leading space
    return "\r\n ".join(chunks)


def _starts_character(raw: bytes, index: int) -> bool:
    return (raw[index] & 0xC0) != 0x80


def _stamp(value: datetime) -> str:
    """Render as UTC.

    The trailing Z is a claim about the zone, so the value has to be moved
    into it first. Appending Z to a local time is off by the offset — eight
    hours, for an appointment stated in Singapore time.
    """
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y%m%dT%H%M%SZ")


def build_ics(entry, now: datetime | None = None) -> str:
    """Render anything with a to_event() as a single-event VCALENDAR."""
    now = now or datetime.now(timezone.utc)
    event = entry.to_event()

    if event.all_day:
        starts = f"DTSTART;VALUE=DATE:{event.start:%Y%m%d}"
        ends = f"DTEND;VALUE=DATE:{event.end:%Y%m%d}"
    else:
        starts = f"DTSTART:{_stamp(event.start)}"
        ends = f"DTEND:{_stamp(event.end)}"

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{event.uid}",
        f"DTSTAMP:{_stamp(now)}",
        starts,
        ends,
        f"SUMMARY:{_ics_escape(event.summary)}",
    ]
    if event.location:
        lines.append(f"LOCATION:{_ics_escape(event.location)}")
    if event.details:
        lines.append(f"DESCRIPTION:{_ics_escape(chr(10).join(event.details))}")
    lines += ["TRANSP:OPAQUE", "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
