# booking-to-caldav

Turns airline booking confirmation emails into events on a CalDAV calendar.

It connects to a mailbox over IMAP, reads messages without marking them as
read, extracts the flight segments it recognises, and writes one event per leg
to a CalDAV collection.

```
IMAP (read-only)  →  parser  →  iCalendar  →  CalDAV (PUT)
```

Python 3.9+, standard library only. No packages to install.

## Supported senders

| Sender | Format |
| --- | --- |
| `booking@singaporeair.com` | "Your booking confirmation ABCDEF" |

Each sender is a module under `booking_to_caldav/parsers/`. Adding one is
described in [Adding a parser](#adding-a-parser).

## Setup

```sh
git clone https://github.com/taikiito-dev/booking-to-caldav
cd booking-to-caldav
cp .env.example .env
$EDITOR .env
```

`.env`:

| Variable | Notes |
| --- | --- |
| `IMAP_HOST`, `IMAP_PORT` | `993` and TLS are assumed |
| `IMAP_USERNAME`, `IMAP_PASSWORD` | an app password is enough; read access only |
| `IMAP_FOLDER` | defaults to `INBOX` |
| `CALDAV_URL` | the collection itself, e.g. `https://dav.example.com/you/personal` |
| `CALDAV_USERNAME`, `CALDAV_PASSWORD` | HTTP Basic |

## Usage

```sh
# parse and print, write nothing
python3 -m booking_to_caldav --dry-run

# write to the calendar
python3 -m booking_to_caldav

# look further back, or at another folder
python3 -m booking_to_caldav --days 365 --limit 500 --folder Archive

# inspect the generated iCalendar text
python3 -m booking_to_caldav --dry-run --show-ics

# list registered parsers
python3 -m booking_to_caldav --list-parsers
```

Run it on a schedule with cron:

```cron
15 6 * * * cd /srv/booking-to-caldav && /usr/bin/python3 -m booking_to_caldav >> /var/log/booking-to-caldav.log 2>&1
```

## Two things confirmation emails leave out

Both are handled in `booking_to_caldav/core.py`.

**The year.** A confirmation prints `24 Dec (Wed)` and never says which year.
The weekday it prints is the way back: of the next few years, usually only one
has 24 December falling on a Wednesday. Candidate dates in the past are
discarded, since a confirmation describes a flight that has not happened yet.
`resolve_year()` raises rather than guessing when no candidate fits.

**The timezone.** Times are local clock times at each airport, with no offset.
The IATA code is the only available key, so `AIRPORT_TZ` maps codes to IANA
timezone names and an unmapped code raises `UnknownAirport` naming the code to
add. Events are written in UTC, so a leg that departs 14:05 in Singapore and
lands 21:40 in Tokyo is stored as `20251224T060500Z` to `20251224T124000Z` —
6h35m, not the 7h35m a naive reading would give.

## Re-running is safe

Each event's UID is derived from the booking reference, the flight number and
the departure time. A second run PUTs to the same URL, so the event is updated
rather than duplicated. Re-importing a whole archive is idempotent.

The IMAP side issues only `SELECT ... readonly`, `SEARCH` and
`FETCH BODY.PEEK` — no flags are set, nothing is moved, nothing is deleted.
Attachments are skipped.

## Adding a parser

1. Copy `booking_to_caldav/parsers/singapore_airlines.py`.
2. Implement `matches(email)` and `parse(email) -> list[Segment]`, then call
   `register()` at the bottom of the module.
3. Import the module in `_load()` in `booking_to_caldav/parsers/__init__.py`.
4. Save an anonymised copy of the email body under `tests/fixtures/` and add a
   test beside `tests/test_singapore_airlines.py`.

Nothing else needs to change. `Segment` and the iCalendar writer are shared.

If a confirmation from a supported sender is not picked up, the body is what
makes it fixable — redact the booking reference, names, seat numbers, payment
details and the `saacrypt`/tracking URLs before attaching it.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

The fixtures are real email layouts with identifying details removed.

## License

MIT
