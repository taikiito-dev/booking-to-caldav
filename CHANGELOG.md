# Changelog

Notable changes per release. Dates are ISO, newest first.

## 0.1.0 — 2026-10-11

First tagged release. Running continuously against a live mailbox since
2026-10-10.

### Added

- Read booking confirmations over IMAP without marking them read, and write
  them to a CalDAV collection as iCalendar events.
- Parser registry: one sender per module under `booking_to_caldav/parsers/`,
  so adding a format is one new file and one line.
- Singapore Airlines confirmations (`booking@singaporeair.com`).
- Calendar invitations (`.ics`) attached to any email. An invitation states its
  own start, end and timezone, so this one parser covers appointment platforms
  — clinics, barbers, some restaurant systems — with no per-sender knowledge.
- `--watch`: IMAP IDLE (RFC 2177), so a confirmation becomes an event within
  seconds on one open connection instead of a poll loop.
- Routing by kind: parsers label a booking `travel` or `local`, and
  `CALDAV_URL_TRAVEL` / `CALDAV_URL_LOCAL` send each to a different collection.
  Every collection named is checked with `PROPFIND` at startup, so a typo is
  reported before any mail is read.
- Year recovery from the weekday a confirmation prints, since confirmations
  omit the year.
- Airport-to-timezone table, since confirmations print local clock times with
  no offset. An unmapped IATA code raises and names itself rather than being
  guessed at.
- Idempotent writes: the UID derives from the booking reference, flight number
  and departure time, so a second run updates rather than duplicates. A whole
  archive can be re-imported safely.
- `systemd` unit in `deploy/`, issue forms for an unread sender and a missing
  airport code, and an installable package (`booking-to-caldav` on the path).

### Fixed

- Timestamps were labelled `Z` without being converted to UTC, so any event
  built from a zone-aware source landed off by that zone's offset. Flights were
  unaffected — they were already converted upstream — and the bug only surfaced
  once invitations were read. Appending `Z` is a claim about the zone, so the
  value has to be moved before the letter goes on.
- `--watch` dropped its connection at the end of every nine-minute idle window
  and waited 60 seconds to reconnect. A timeout raised out of Python's buffered
  socket reader leaves it permanently unusable, so waiting with `settimeout`
  cannot work; the window is now waited out with `select`, which expires
  without reading at all.

### Known limits

- Flights: Singapore Airlines only. Other airlines are not guessed at —
  a parser needs a real email, so
  [open an issue](https://github.com/taikiito-dev/booking-to-caldav/issues/new?template=unsupported-sender.yml)
  with a redacted one.
- Restaurant platforms that send prose instead of an invitation are not read
  yet.
- A repeating invitation contributes its first occurrence only.
