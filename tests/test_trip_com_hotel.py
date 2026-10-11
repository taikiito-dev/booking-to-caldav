"""Tests for a hotel confirmation that arrived as a forward.

The fixture is the real Trip.com layout with the hotel, address, dates, names
and numbers replaced.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from booking_to_caldav.core import (  # noqa: E402
    TRAVEL,
    Stay,
    UnknownStayLocation,
    build_ics,
    stay_tz,
)
from booking_to_caldav.parsers import Email, parse  # noqa: E402
from booking_to_caldav.parsers.forwarded import unwrap  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


class ForwardedHotelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.email = Email(
            subject="Fwd: [予約確認] ホテルサンプル神戸のご予約の確認が完了しました-NoReply",
            sender="Example Sender <someone@example.com>",
            body=(FIXTURES / "trip_com_hotel_kobe_forwarded.txt").read_text(
                encoding="utf-8"
            ),
            received=date(2027, 10, 12),
        )
        self.events = parse(self.email)

    def test_the_forward_is_unwrapped_to_the_original_sender(self) -> None:
        """No parser matches a person; they all match the booking site."""
        inner = unwrap(self.email)
        self.assertIsNotNone(inner)
        self.assertEqual(inner.sender, "JP_HTL_NoReply@trip.com")
        self.assertFalse(inner.subject.lower().startswith("fwd"))

    def test_one_event_per_night(self) -> None:
        self.assertEqual(len(self.events), 1)

    def test_the_night_is_an_evening_block_in_hotel_local_time(self) -> None:
        event = self.events[0]
        self.assertEqual(event.summary, "Stay at ホテルサンプル神戸")
        self.assertEqual(
            event.start, datetime(2027, 11, 6, 10, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(event.end, datetime(2027, 11, 6, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(event.category, TRAVEL)

    def test_the_booking_number_survives_its_zero_width_padding(self) -> None:
        """Trip.com pads the digits so clients do not linkify them."""
        details = "\n".join(self.events[0].details)
        self.assertIn("Booking reference: 1234567890123456", details)

    def test_the_real_check_in_times_are_kept_in_the_description(self) -> None:
        details = "\n".join(self.events[0].details)
        self.assertIn("Check-in 2027-11-06 15:00", details)
        self.assertIn("check-out 2027-11-07 12:00", details)

    def test_the_guest_is_the_field_and_not_the_sentence(self) -> None:
        details = "\n".join(self.events[0].details)
        self.assertIn("Guest: EXAMPLE GUEST", details)
        self.assertNotIn("Guest: と", details)

    def test_japanese_text_folds_without_splitting_a_character(self) -> None:
        ics = build_ics(self.events[0])
        self.assertIn("ホテルサンプル神戸", ics.replace("\r\n ", ""))
        for line in ics.split("\r\n"):
            self.assertLessEqual(len(line.encode("utf-8")), 75)


class StayTest(unittest.TestCase):
    def stay(self, nights: int) -> Stay:
        return Stay(
            hotel="Example Hotel",
            address="1 Example Street, Singapore",
            check_in=date(2027, 3, 1),
            check_out=date(2027, 3, 1 + nights),
            booking_ref="REF123",
        )

    def test_a_three_night_booking_becomes_three_events(self) -> None:
        events = self.stay(3).events()
        self.assertEqual(len(events), 3)
        self.assertEqual(
            [event.start.date() for event in events],
            [date(2027, 3, 1), date(2027, 3, 2), date(2027, 3, 3)],
        )
        self.assertEqual(events[0].summary, "Stay at Example Hotel (1/3)")
        self.assertEqual(events[2].summary, "Stay at Example Hotel (3/3)")

    def test_nights_have_distinct_stable_uids(self) -> None:
        first = [event.uid for event in self.stay(2).events()]
        again = [event.uid for event in self.stay(2).events()]
        self.assertEqual(first, again)
        self.assertEqual(len(set(first)), 2)

    def test_a_same_day_booking_still_counts_as_one_night(self) -> None:
        stay = Stay(
            hotel="Example Hotel",
            address="Tokyo, Japan",
            check_in=date(2027, 3, 1),
            check_out=date(2027, 3, 1),
            booking_ref="REF123",
        )
        self.assertEqual(len(stay.events()), 1)

    def test_an_address_with_no_hint_raises_instead_of_guessing(self) -> None:
        with self.assertRaises(UnknownStayLocation):
            stay_tz("12 Nowhere Lane")


class NotAForwardTest(unittest.TestCase):
    def test_plain_prose_is_not_treated_as_a_forward(self) -> None:
        message = Email(
            subject="lunch?",
            sender="friend@example.com",
            body="Are you free on Thursday? I forwarded you the menu earlier.",
            received=date(2027, 1, 1),
        )
        self.assertIsNone(unwrap(message))
        self.assertEqual(parse(message), [])


if __name__ == "__main__":
    unittest.main()
