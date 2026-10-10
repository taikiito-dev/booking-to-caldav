"""Singapore Airlines booking confirmations (booking@singaporeair.com).

The plain-text alternative of these emails prints each leg as:

    SQ 634 • Airbus A350-900
    Economy
    24 Dec (Wed)
    SIN 14:05
    Singapore
    Changi
    Terminal 2
    24 Dec (Wed)
    HND 21:40
    Tokyo
    Haneda Intl
    Terminal 3

Two things are missing from every date: the year and the timezone. The year is
recovered from the weekday the email prints (see core.resolve_year) and the
timezone from the IATA code (see core.AIRPORT_TZ).
"""

from __future__ import annotations

import re
from datetime import datetime

from ..core import MONTHS, Segment, resolve_year
from . import Email, Parser, register

FLIGHT = re.compile(r"\b([A-Z]{2})\s*(\d{1,4})\s*[•·•]\s*([^\r\n]*)")

STOP = re.compile(
    r"(\d{1,2})\s+([A-Z][a-z]{2})\s*\(([A-Za-z]{3})\)\s*[\r\n]+\s*"
    r"([A-Z]{3})\s+(\d{1,2}):(\d{2})"
)

TERMINAL = re.compile(r"Terminal\s+([0-9A-Za-z]+)")

CABIN = re.compile(
    r"\b(Suites|First Class|First|Business Class|Business|"
    r"Premium Economy|Economy)\b"
)

REF_IN_SUBJECT = re.compile(r"\b([A-Z0-9]{6})\b")
REF_IN_BODY = re.compile(r"BOOKING REFERENCE\s*[\r\n]+\s*([A-Z0-9]{6})\b")


class SingaporeAirlines(Parser):
    name = "Singapore Airlines (booking@singaporeair.com)"

    def matches(self, email: Email) -> bool:
        haystack = f"{email.sender} {email.body}".lower()
        if "singaporeair.com" not in haystack:
            return False
        subject = email.subject.lower()
        return (
            "booking confirmation" in subject
            or "booking is confirmed" in email.body.lower()
        )

    def booking_ref(self, email: Email) -> str | None:
        in_body = REF_IN_BODY.search(email.body)
        if in_body:
            return in_body.group(1)
        # "Your booking confirmation ABCDEF"
        tail = email.subject.split("confirmation")[-1]
        in_subject = REF_IN_SUBJECT.search(tail)
        return in_subject.group(1) if in_subject else None

    def parse(self, email: Email) -> list[Segment]:
        ref = self.booking_ref(email)
        if not ref:
            return []

        body = email.body
        flights = list(FLIGHT.finditer(body))
        segments: list[Segment] = []

        for index, flight in enumerate(flights):
            end = flights[index + 1].start() if index + 1 < len(flights) else len(body)
            block = body[flight.end() : end]

            stops = list(STOP.finditer(block))
            if len(stops) < 2:
                continue  # not an itinerary block (e.g. a flight named in prose)
            departure, arrival = stops[0], stops[1]

            try:
                depart = self._instant(departure, email)
                arrive = self._instant(arrival, email)
            except (ValueError, KeyError):
                continue

            cabin = CABIN.search(block[: departure.start()])
            segments.append(
                Segment(
                    carrier=flight.group(1),
                    number=flight.group(2),
                    origin=departure.group(4).upper(),
                    destination=arrival.group(4).upper(),
                    depart_local=depart,
                    arrive_local=arrive,
                    booking_ref=ref,
                    cabin=cabin.group(1) if cabin else None,
                    aircraft=(flight.group(3).strip() or None),
                    origin_terminal=self._terminal(
                        block[departure.end() : arrival.start()]
                    ),
                    destination_terminal=self._terminal(block[arrival.end() :]),
                    source=self.name,
                )
            )

        return _deduplicate(segments)

    @staticmethod
    def _instant(stop: re.Match[str], email: Email) -> datetime:
        day = int(stop.group(1))
        month = MONTHS[stop.group(2).title()]
        weekday = stop.group(3)
        year = resolve_year(day, month, weekday, email.received)
        return datetime(year, month, day, int(stop.group(5)), int(stop.group(6)))

    @staticmethod
    def _terminal(text: str) -> str | None:
        found = TERMINAL.search(text)
        return found.group(1) if found else None


def _deduplicate(segments: list[Segment]) -> list[Segment]:
    """These emails repeat the itinerary in a mobile layout further down."""
    seen: set[str] = set()
    unique = []
    for segment in segments:
        if segment.uid in seen:
            continue
        seen.add(segment.uid)
        unique.append(segment)
    return unique


register(SingaporeAirlines())
