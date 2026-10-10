"""Command line entry point.

    python3 -m booking_to_caldav --dry-run     # print what would be written
    python3 -m booking_to_caldav               # run once, then exit
    python3 -m booking_to_caldav --watch       # stay connected, react on arrival

Configuration comes from the environment (see .env.example). Nothing reaches
the calendar on a dry run.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .calendar_sink import Calendar
from .core import LOCAL, TRAVEL, Segment, UnknownAirport, build_ics
from .mailbox import Mailbox
from .parsers import Email, all_parsers, parse

REQUIRED = (
    "IMAP_HOST",
    "IMAP_USERNAME",
    "IMAP_PASSWORD",
    "CALDAV_URL",
    "CALDAV_USERNAME",
    "CALDAV_PASSWORD",
)

IDLE_SECONDS = 540  # re-issue IDLE well inside the 29 minute limit in RFC 2177
RECONNECT_SECONDS = 60


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


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{stamp} {message}", flush=True)


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
        "--watch",
        action="store_true",
        help="stay connected and react when mail arrives (IMAP IDLE)",
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
        "--include-past",
        action="store_true",
        help="also write flights that have already departed (skipped by default)",
    )
    parser.add_argument(
        "--show-ics", action="store_true", help="print the generated iCalendar text"
    )
    parser.add_argument(
        "--list-parsers", action="store_true", help="list registered parsers and exit"
    )
    return parser


def collect(messages: list[Email]) -> list[Segment]:
    segments: list[Segment] = []
    for message in messages:
        try:
            found = parse(message)
        except UnknownAirport as error:
            log(f"  skipped {message.subject!r}: {error}")
            continue
        if found:
            log(f"  matched: {message.subject}")
            segments.extend(found)
    return segments


def publish(
    segments: list[Segment],
    destinations: "Destinations | None",
    include_past: bool,
    show_ics: bool,
) -> int:
    """Write segments to their calendars. Returns the number of events written."""
    now = datetime.now(timezone.utc)
    written = 0

    for entry in segments:
        event = entry.to_event()
        label = event.label or event.summary
        # An all-day event carries a naive date; read it as UTC for the
        # past check rather than refusing to compare.
        moment = event.start
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if not include_past and moment < now:
            log(f"  past, skipped {label}")
            continue

        ics = build_ics(event, now=now)
        if show_ics:
            print(ics)
        if destinations is None:
            log(f"  would write {label} -> {calendar_url_for(event.category)}")
            continue

        calendar = destinations.for_category(event.category)
        result = calendar.put(event.uid, ics)
        if result.ok:
            written += 1
            verb = "created" if result.created else "updated"
        else:
            verb = "FAILED"
        log(f"  {verb} {label}  [HTTP {result.status}]")

    return written


def calendar_url_for(category: str) -> str:
    """Where events of this kind go.

    CALDAV_URL_TRAVEL and CALDAV_URL_LOCAL route by kind; CALDAV_URL is the
    fallback for whatever is not routed. Setting only CALDAV_URL keeps
    everything in one place.
    """
    specific = os.environ.get(f"CALDAV_URL_{category.upper()}")
    return specific or os.environ["CALDAV_URL"]


class Destinations:
    """One checked, reused Calendar per distinct URL."""

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._calendars: dict[str, Calendar] = {}

    def for_category(self, category: str) -> Calendar:
        url = calendar_url_for(category)
        if url not in self._calendars:
            calendar = Calendar(url, self._username, self._password)
            status = calendar.check()
            if status not in (200, 207):
                raise RuntimeError(
                    f"{url} did not answer PROPFIND as expected (HTTP {status}); "
                    "check it points at the collection itself and the credentials"
                )
            self._calendars[url] = calendar
        return self._calendars[url]

    def check_all(self, categories: tuple[str, ...]) -> None:
        for category in categories:
            self.for_category(category)

    def describe(self) -> str:
        return ", ".join(sorted(self._calendars))


def open_destinations(dry_run: bool) -> Destinations | None:
    if dry_run:
        return None
    destinations = Destinations(
        username=os.environ["CALDAV_USERNAME"],
        password=os.environ["CALDAV_PASSWORD"],
    )
    destinations.check_all((TRAVEL, LOCAL))
    return destinations


def run_once(args: argparse.Namespace, destinations: "Destinations | None") -> int:
    with Mailbox(
        host=os.environ["IMAP_HOST"],
        port=int(os.environ.get("IMAP_PORT", "993")),
        username=os.environ["IMAP_USERNAME"],
        password=os.environ["IMAP_PASSWORD"],
        folder=args.folder,
    ) as mailbox:
        messages = mailbox.recent(days=args.days, limit=args.limit)
    log(f"examined {len(messages)} message(s) in {args.folder}")
    segments = collect(messages)
    if not segments:
        log("no flight segments found")
        return 0
    return publish(segments, destinations, args.include_past, args.show_ics)


def run_watch(args: argparse.Namespace, destinations: "Destinations | None") -> int:
    """Open the mailbox once and let the server announce arrivals."""
    while True:
        try:
            with Mailbox(
                host=os.environ["IMAP_HOST"],
                port=int(os.environ.get("IMAP_PORT", "993")),
                username=os.environ["IMAP_USERNAME"],
                password=os.environ["IMAP_PASSWORD"],
                folder=args.folder,
            ) as mailbox:
                mode = "IDLE" if mailbox.supports_idle else "polling (no IDLE)"
                log(f"watching {args.folder} via {mode}")

                messages = mailbox.recent(days=args.days, limit=args.limit)
                log(f"initial sweep: {len(messages)} message(s)")
                publish(collect(messages), destinations, args.include_past, args.show_ics)

                while True:
                    arrived = mailbox.wait_for_mail(IDLE_SECONDS)
                    if not arrived:
                        continue  # idle window expired; just re-issue
                    log("mail arrived")
                    fresh = mailbox.recent(days=1, limit=20)
                    publish(
                        collect(fresh), destinations, args.include_past, args.show_ics
                    )
        except KeyboardInterrupt:
            log("stopped")
            return 0
        except Exception as error:  # a dropped connection must not end the service
            log(f"connection problem: {error!r}; reconnecting in {RECONNECT_SECONDS}s")
            time.sleep(RECONNECT_SECONDS)


def main(argv: list[str] | None = None) -> int:
    load_env_file(Path.cwd() / ".env")
    args = build_arg_parser().parse_args(argv)

    if args.list_parsers:
        for parser in all_parsers():
            print(f"- {parser.name}")
        return 0

    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        print(f"missing configuration: {', '.join(missing)}", file=sys.stderr)
        print("copy .env.example to .env and fill it in", file=sys.stderr)
        return 2

    try:
        destinations = open_destinations(args.dry_run)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    if destinations:
        log(f"destinations: {destinations.describe()}")

    if args.watch:
        return run_watch(args, destinations)

    run_once(args, destinations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
