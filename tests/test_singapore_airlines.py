"""Tests run on the real email layout, anonymised in tests/fixtures/."""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from booking_to_caldav.core import UnknownAirport, build_ics, resolve_year  # noqa: E402
from booking_to_caldav.parsers import Email, parse  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str, received: date, subject: str, sender: str) -> Email:
    return Email(
        subject=subject,
        sender=sender,
        body=(FIXTURES / name).read_text(encoding="utf-8"),
        received=received,
    )


class SingaporeAirlinesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.email = load(
            "singapore_airlines_sin_hnd.txt",
            received=date(2025, 9, 28),
            subject="Your booking confirmation ABCDEF",
            sender="booking@singaporeair.com",
        )
        self.segments = parse(self.email)

    def test_finds_both_legs_once_each(self) -> None:
        self.assertEqual(len(self.segments), 2)
        self.assertEqual(
            [segment.flight for segment in self.segments], ["SQ634", "SQ633"]
        )

    def test_outbound_leg(self) -> None:
        leg = self.segments[0]
        self.assertEqual((leg.origin, leg.destination), ("SIN", "HND"))
        self.assertEqual(leg.depart_local, datetime(2025, 12, 24, 14, 5))
        self.assertEqual(leg.arrive_local, datetime(2025, 12, 24, 21, 40))
        self.assertEqual(leg.booking_ref, "ABCDEF")
        self.assertEqual(leg.cabin, "Economy")
        self.assertEqual(leg.aircraft, "Airbus A350-900")
        self.assertEqual(leg.origin_terminal, "2")
        self.assertEqual(leg.destination_terminal, "3")

    def test_return_leg_rolls_into_the_next_year(self) -> None:
        """The email says "04 Jan (Sun)" and never says 2026."""
        leg = self.segments[1]
        self.assertEqual(leg.depart_local, datetime(2026, 1, 4, 16, 40))
        self.assertEqual(leg.arrive_local, datetime(2026, 1, 4, 23, 20))

    def test_local_clock_times_become_the_right_instant(self) -> None:
        leg = self.segments[0]
        # 14:05 in Singapore (UTC+8) departs at 06:05Z;
        # 21:40 in Tokyo (UTC+9) arrives at 12:40Z — a 6h35m flight.
        self.assertEqual(leg.depart_utc.strftime("%Y%m%dT%H%M%SZ"), "20251224T060500Z")
        self.assertEqual(leg.arrive_utc.strftime("%Y%m%dT%H%M%SZ"), "20251224T124000Z")
        self.assertEqual((leg.arrive_utc - leg.depart_utc).total_seconds(), 6 * 3600 + 2100)

    def test_uid_is_stable_so_reimport_updates(self) -> None:
        again = parse(self.email)
        self.assertEqual(
            [segment.uid for segment in self.segments],
            [segment.uid for segment in again],
        )

    def test_ics_is_well_formed(self) -> None:
        ics = build_ics(self.segments[0], now=datetime(2025, 9, 28, 12, 0, 0))
        self.assertTrue(ics.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(ics.rstrip().endswith("END:VCALENDAR"))
        self.assertIn("DTSTART:20251224T060500Z", ics)
        self.assertIn("DTEND:20251224T124000Z", ics)
        self.assertIn("SUMMARY:SQ634 SIN → HND", ics)
        self.assertIn("ABCDEF", ics)
        for line in ics.split("\r\n"):
            self.assertLessEqual(len(line.encode()), 75, f"unfolded line: {line!r}")

    def test_unrelated_email_is_ignored(self) -> None:
        other = Email(
            subject="Your booking confirmation",
            sender="no-reply@setmore.com",
            body="Appointment booked with the barber.",
            received=date(2026, 10, 6),
        )
        self.assertEqual(parse(other), [])


class YearInferenceTest(unittest.TestCase):
    def test_weekday_picks_the_year(self) -> None:
        # 24 Dec is a Wednesday in 2025, a Thursday in 2026.
        self.assertEqual(resolve_year(24, 12, "Wed", date(2025, 9, 28)), 2025)
        self.assertEqual(resolve_year(24, 12, "Thu", date(2025, 9, 28)), 2026)

    def test_past_dates_are_not_chosen(self) -> None:
        """A confirmation received in December is about next January, not last."""
        self.assertEqual(resolve_year(4, 1, "Sun", date(2025, 12, 28)), 2026)

    def test_no_weekday_falls_back_to_the_next_occurrence(self) -> None:
        self.assertEqual(resolve_year(4, 1, None, date(2025, 12, 28)), 2026)

    def test_impossible_date_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_year(24, 12, "Mon", date(2025, 9, 28), horizon_years=0)


class AirportTest(unittest.TestCase):
    def test_unknown_airport_names_itself(self) -> None:
        with self.assertRaises(UnknownAirport):
            from booking_to_caldav.core import airport_tz

            airport_tz("ZZZ")


if __name__ == "__main__":
    unittest.main(verbosity=2)
