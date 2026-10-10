"""Command line entry point.

    python -m booking_to_caldav --dry-run        # print what would be written
    python -m booking_to_caldav                  # write to the calendar

Configuration comes from the environment (see .env.example). Nothing is
written to the calendar unless the run is not a dry run.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .calendar_sink import Calendar
from .core import UnknownAirport, build_ics
from .mailbox import Mailbox
from .parsers import all_parsers, parse

REQUIRED = (
    "IMAP_HOST",
    "IMAP_USERNAME",
    "IMAP_PASSWORD",
    "CALDAV_URL",
    "CALDAV_USERNAME",
    "CALDAV_PASSWORD",
)


def load_env_file(path: Path) -> None:
    """Minimal .env reader so the tool runs without extra dependencies."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="booking_to_caldav",
        description="Turn airline booking confirmation emails into calendar events.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse and print, write nothing to the calendar",
    )
    parser.add_argument(
        "--days", type=int, default=30, help="how far back to look (default: 30)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="most recent N messages to examine (default: 200)",
    )
    parser.add_argument(
        "--folder",
        default=os.environ.get("IMAP_FOLDER", "INBOX"),
        help="IMAP folder to read (default: INBOX)",
    )
    parser.add_argument(
        "--show-ics", action="store_true", help="print the generated iCalendar text"
    )
    parser.add_argument(
        "--list-parsers", action="store_true", help="list registered parsers and exit"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_env_file(Path.cwd() / ".env")
    args = build_arg_parser().parse_args(argv)

    if args.list_parsers:
        for parser in all_parsers():
            print(f"- {parser.name}")
        return 0

    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing and not (args.dry_run and not _imap_missing(missing)):
        print(f"missing configuration: {', '.join(missing)}", file=sys.stderr)
        print("copy .env.example to .env and fill it in", file=sys.stderr)
        return 2

    with Mailbox(
        host=os.environ["IMAP_HOST"],
        port=int(os.environ.get("IMAP_PORT", "993")),
        username=os.environ["IMAP_USERNAME"],
        password=os.environ["IMAP_PASSWORD"],
        folder=args.folder,
    ) as mailbox:
        messages = mailbox.recent(days=args.days, limit=args.limit)

    print(f"examined {len(messages)} message(s) in {args.folder}")

    segments = []
    for message in messages:
        try:
            found = parse(message)
        except UnknownAirport as error:
            print(f"  skipped {message.subject!r}: {error}", file=sys.stderr)
            continue
        if found:
            print(f"  matched: {message.subject}")
            segments.extend(found)

    if not segments:
        print("no flight segments found")
        return 0

    now = datetime.now(timezone.utc)
    calendar = None
    if not args.dry_run:
        calendar = Calendar(
            url=os.environ["CALDAV_URL"],
            username=os.environ["CALDAV_USERNAME"],
            password=os.environ["CALDAV_PASSWORD"],
        )
        status = calendar.check()
        if status >= 400:
            print(f"calendar is not reachable (HTTP {status})", file=sys.stderr)
            return 1

    for segment in segments:
        label = (
            f"{segment.flight} {segment.origin}->{segment.destination} "
            f"{segment.depart_local:%Y-%m-%d %H:%M} ({segment.booking_ref})"
        )
        ics = build_ics(segment, now=now)
        if args.show_ics:
            print(ics)
        if calendar is None:
            print(f"  would write {label}")
            continue
        result = calendar.put(segment.uid, ics)
        verb = "created" if result.created else "updated" if result.updated else "FAILED"
        print(f"  {verb} {label}  [HTTP {result.status}]")

    return 0


def _imap_missing(missing: list[str]) -> bool:
    return any(name.startswith("IMAP_") for name in missing)


if __name__ == "__main__":
    raise SystemExit(main())
