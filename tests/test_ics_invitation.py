"""Tests for invitations attached to an email."""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from booking_to_caldav.core import LOCAL, build_ics  # noqa: E402
from booking_to_caldav.parsers import Email, parse  # noqa: E402

CLINIC = """BEGIN:VCALENDAR
VERSION:2.0
METHOD:REQUEST
BEGIN:VEVENT
UID:booking-99887766@example-clinic.com
DTSTAMP:20261001T090000Z
DTSTART;TZID=Asia/Singapore:20261011T143000
DTEND;TZID=Asia/Singapore:20261011T153000
SUMMARY:Appointment at Example Dental
LOCATION:1 Example Road\\, Singapore
DESCRIPTION:Please arrive ten minutes early.
END:VEVENT
END:VCALENDAR
"""

FOLDED = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:folded-1@example.com
DTSTART:20261011T020000Z
DURATION:PT90M
SUMMARY:A summary that has been split across
  two physical lines
END:VEVENT
END:VCALENDAR
"""

CANCELLED = """BEGIN:VCALENDAR
VERSION:2.0
METHOD:CANCEL
BEGIN:VEVENT
UID:booking-99887766@example-clinic.com
DTSTART:20261011T063000Z
SUMMARY:Appointment at Example Dental
END:VEVENT
END:VCALENDAR
"""

ALL_DAY = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:allday-1@example.com
DTSTART;VALUE=DATE:20261220
DTEND;VALUE=DATE:20261221
SUMMARY:Public holiday
END:VEVENT
END:VCALENDAR
"""


def invitation(payload: str, subject: str = "Appointment Booked") -> Email:
    return Email(
        subject=subject,
        sender="no-reply@example-clinic.com",
        body="Your appointment is confirmed.",
        received=date(2026, 10, 1),
        calendars=(payload,),
    )


class InvitationTest(unittest.TestCase):
    def test_reads_the_stated_timezone(self) -> None:
        event = parse(invitation(CLINIC))[0].to_event()
        # 14:30 in Singapore is 06:30 UTC.
        self.assertEqual(
            event.start.astimezone(timezone.utc),
            datetime(2026, 10, 11, 6, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(
            event.end.astimezone(timezone.utc),
            datetime(2026, 10, 11, 7, 30, tzinfo=timezone.utc),
        )

    def test_keeps_summary_location_and_description(self) -> None:
        event = parse(invitation(CLINIC))[0].to_event()
        self.assertEqual(event.summary, "Appointment at Example Dental")
        self.assertEqual(event.location, "1 Example Road, Singapore")
        self.assertIn("Please arrive ten minutes early.", event.details[0])

    def test_goes_to_the_local_calendar(self) -> None:
        self.assertEqual(parse(invitation(CLINIC))[0].to_event().category, LOCAL)

    def test_does_not_reuse_the_senders_uid(self) -> None:
        """Reusing it would overwrite the copy the mail client already made."""
        uid = parse(invitation(CLINIC))[0].to_event().uid
        self.assertNotEqual(uid, "booking-99887766@example-clinic.com")
        self.assertTrue(uid.endswith("-ics@booking-to-caldav"))

    def test_uid_is_stable_across_runs(self) -> None:
        first = parse(invitation(CLINIC))[0].to_event().uid
        second = parse(invitation(CLINIC))[0].to_event().uid
        self.assertEqual(first, second)

    def test_cancellations_are_ignored(self) -> None:
        self.assertEqual(parse(invitation(CANCELLED)), [])

    def test_folded_lines_and_duration(self) -> None:
        event = parse(invitation(FOLDED))[0].to_event()
        self.assertEqual(
            event.summary, "A summary that has been split across two physical lines"
        )
        self.assertEqual((event.end - event.start).total_seconds(), 90 * 60)

    def test_all_day_event_is_written_as_a_date(self) -> None:
        event = parse(invitation(ALL_DAY))[0].to_event()
        self.assertTrue(event.all_day)
        ics = build_ics(event, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
        self.assertIn("DTSTART;VALUE=DATE:20261220", ics)
        self.assertIn("DTEND;VALUE=DATE:20261221", ics)

    def test_email_without_an_invitation_is_not_claimed(self) -> None:
        plain = Email(
            subject="Appointment Booked",
            sender="no-reply@example-clinic.com",
            body="Your appointment is confirmed.",
            received=date(2026, 10, 1),
        )
        self.assertEqual(parse(plain), [])

    def test_output_is_well_formed(self) -> None:
        event = parse(invitation(CLINIC))[0].to_event()
        ics = build_ics(event, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
        self.assertTrue(ics.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertIn("DTSTART:20261011T063000Z", ics)
        for line in ics.split("\r\n"):
            self.assertLessEqual(len(line.encode()), 75, f"unfolded line: {line!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
