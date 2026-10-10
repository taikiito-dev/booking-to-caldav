# booking-to-caldav

[![tests](https://github.com/taikiito-dev/booking-to-caldav/actions/workflows/test.yml/badge.svg)](https://github.com/taikiito-dev/booking-to-caldav/actions/workflows/test.yml)

Turns booking confirmation emails into events on a CalDAV calendar.

It connects to a mailbox over IMAP, reads messages without marking them as
read, extracts the bookings it recognises, and writes them to a CalDAV
collection.

```
IMAP (read-only)  →  parser  →  iCalendar  →  CalDAV (PUT)
```

Python 3.9+, standard library only. No packages to install.

## Supported senders

| Sender | Format |
| --- | --- |
| any | a calendar invitation (`.ics`) attached to the email |
| `booking@singaporeair.com` | "Your booking confirmation ABCDEF" |

The first row covers more than it looks like. Appointment platforms —
clinics, barbers, some restaurant systems — attach an invitation, and an
invitation states its own start, end and timezone. So that parser needs no
knowledge of the sender at all, and a new platform usually works on the day
it appears.

`METHOD:CANCEL` and `METHOD:REPLY` are ignored: removing an event the user
may have edited is a larger decision than adding one, and a reply is somebody
else's answer rather than a booking. A repeating invitation contributes its
first occurrence, with a note in the description saying so.

Invitations are written with their own namespaced UID rather than the
sender's. Reusing the sender's would overwrite the copy a mail client created
when the invitation was accepted, replacing a complete event — attendees and
all — with this reconstruction of it.

Each sender is a module under `booking_to_caldav/parsers/`. Adding one is
described in [Adding a parser](#adding-a-parser).

## Setup

```sh
git clone https://github.com/taikiito-dev/booking-to-caldav
cd booking-to-caldav
cp .env.example .env
$EDITOR .env
```

There is nothing to install — `python3 -m booking_to_caldav` runs from the
clone. To put it on the path instead:

```sh
pipx install git+https://github.com/taikiito-dev/booking-to-caldav
booking-to-caldav --dry-run
```

Either way the `.env` read is the one in the directory the command is run
from, so an installed copy still needs a working directory to be started in.

`.env`:

| Variable | Notes |
| --- | --- |
| `IMAP_HOST`, `IMAP_PORT` | `993` and TLS are assumed |
| `IMAP_USERNAME`, `IMAP_PASSWORD` | an app password is enough; read access only |
| `IMAP_FOLDER` | defaults to `INBOX` |
| `CALDAV_URL` | the collection itself, e.g. `https://dav.example.com/you/personal` |
| `CALDAV_URL_TRAVEL` | optional; where flights, trains and hotels go |
| `CALDAV_URL_LOCAL` | optional; where appointments near home go |
| `CALDAV_USERNAME`, `CALDAV_PASSWORD` | HTTP Basic |
| `DEFAULT_TIMEZONE` | IANA name, for invitations that state no zone at all; defaults to `UTC` |

### Two kinds of booking

A flight takes you away from home, and somebody else in the household may
need to know. A haircut does not. Parsers label what they found `travel` or
`local`, and the two optional variables above send each kind to a different
collection. With only `CALDAV_URL` set, everything lands in one place.

Every collection named is checked at startup, so a typo in either one is
reported before any mail is read rather than on the day a booking arrives.

## Usage

```sh
# parse and print, write nothing
python3 -m booking_to_caldav --dry-run

# run once and exit
python3 -m booking_to_caldav

# stay connected and react when mail arrives
python3 -m booking_to_caldav --watch

# look further back, or at another folder
python3 -m booking_to_caldav --days 365 --limit 500 --folder Archive

# flights that already departed are skipped; this writes them anyway
python3 -m booking_to_caldav --include-past

# inspect the generated iCalendar text
python3 -m booking_to_caldav --dry-run --show-ics

# list registered parsers
python3 -m booking_to_caldav --list-parsers
```

## Running continuously

`--watch` uses IMAP IDLE (RFC 2177). The connection is held open and the
server sends an untagged `EXISTS` when mail arrives, so a confirmation becomes
an event within seconds without polling. IDLE is re-issued every nine minutes,
inside the twenty-nine minute limit the RFC sets. Between arrivals the process
is blocked on a socket read: one open connection, no CPU.

The window is waited out with `select`, not a socket timeout. A timeout
raised out of Python's buffered reader leaves it unusable — every later read
fails with `cannot read from timed out object` — which costs a reconnect
every single window and leaves a gap each time. `select` lets the window
expire without reading at all, so one connection survives indefinitely.

A dropped connection is still expected rather than exceptional — servers,
networks and restarts all end IDLE sessions. The watcher reconnects and
re-sweeps, which is safe because writes are idempotent.

`IDLE_SECONDS` overrides the window length, which is mostly useful for
exercising the expiry path without waiting nine minutes.

```sh
sudo useradd --system --home /srv/booking-to-caldav booking-to-caldav
sudo cp -r . /srv/booking-to-caldav
sudo install -m 600 -o booking-to-caldav .env /srv/booking-to-caldav/.env
sudo cp deploy/booking-to-caldav.service /etc/systemd/system/
sudo systemctl enable --now booking-to-caldav
journalctl -u booking-to-caldav -f
```

`cron` still works if a daily sweep is preferable to a resident process:

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
What a pull request is expected to carry is in
[CONTRIBUTING.md](CONTRIBUTING.md).

If you would rather not write one, open an issue with the redacted email body
and that is enough to work from. There are two issue forms — one for a sender
that is not read yet, one for a missing airport code — and both list what to
remove before pasting.

A parser cannot be written from a description of the layout. The line breaks
and the exact wording are the whole problem.

## Troubleshooting

**Every calendar request returns 403, but the same request from curl works.**
Something in front of the calendar — a WAF, Cloudflare, a reverse proxy rule —
is blocking the client by name. `urllib`'s default `Python-urllib/3.x` is a
common blocklist entry. This project sends its own `User-Agent` for that
reason; if a deployment still rejects it, allow that string at the proxy.

**`OPTIONS` returns 403 while `PUT` succeeds.** Proxies in front of CalDAV
often answer `OPTIONS` themselves. That makes it useless as a liveness test,
which is why `check()` uses `PROPFIND` and expects 207.

**A confirmation is not picked up.** Run with `--dry-run --days 365 --folder
Archive` to widen the search, and `--list-parsers` to confirm the sender is
supported at all. Flights that already departed are skipped unless
`--include-past` is given.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

The fixtures are real email layouts with identifying details removed.

The same command runs in CI on Python 3.9 through 3.13, with no install step,
so a green badge also confirms the project still needs no packages.

## License

MIT
