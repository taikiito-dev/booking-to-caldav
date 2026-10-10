# Contributing

Every booking confirmation in the world is laid out differently, and this
project can only read the ones somebody has actually seen. That makes a
redacted email a complete contribution — no code required.

## An email is enough

Open an issue and paste the body. Two forms exist:

- **[A sender that is not read yet](https://github.com/taikiito-dev/booking-to-caldav/issues/new?template=unsupported-sender.yml)**
- **[A missing airport code](https://github.com/taikiito-dev/booking-to-caldav/issues/new?template=unknown-airport.yml)** — two fields, and the fix is one line

Both forms list what to remove first. The short version: booking reference,
name, seat, fare, and any link that would log someone in as you.

Paste the body itself, not a description of it. A parser is written against
line breaks and exact wording, so "the date is above the flight number" is not
something that can be turned into code. Keeping the layout intact — including
the blank lines — is the whole value of the report.

## A parser, if you want to write one

The recipe is in the README under
[Adding a parser](README.md#adding-a-parser). Four steps, one new file, one
line in the registry. `Segment`, `Event` and the iCalendar writer are shared,
so a parser only answers two questions: is this email mine, and what is in it.

```sh
git clone https://github.com/<you>/booking-to-caldav
cd booking-to-caldav
git switch -c read-<sender>
python3 -m unittest discover -s tests -v
```

Then open a pull request. CI runs the same test command on Python 3.9 through
3.13 and installs nothing, so a green run also confirms the project still
needs no packages.

### What a pull request needs

- **A fixture and a test.** Save the anonymised body under `tests/fixtures/`
  and assert the times you expect out of it. A parser without a fixture cannot
  be maintained by anyone who does not receive that sender's mail — which is
  everybody else.
- **Times asserted in UTC.** Local clock times hide the bug that matters. An
  event written an hour or eight hours off still looks plausible in a diff.
- **A raise instead of a guess.** When the year, the timezone or the sender is
  unclear, raise and name what is missing. A wrong event in a calendar is worse
  than a missing one, because nobody re-checks it.

Formatting follows what is already in the file. There is no linter to satisfy.

## Out of scope

- **Writing to the mailbox.** The IMAP side stays read-only: `SELECT ...
  readonly`, `SEARCH`, `FETCH BODY.PEEK`. No flags, no moves, no deletes.
- **Dependencies.** A new package has to earn its place against five years of
  unattended uptime. Standard library or nothing.
- **Deleting or editing events the user owns.** `METHOD:CANCEL` and
  `METHOD:REPLY` are ignored on purpose.
- **Hosting, UI, a web dashboard.** This is one process that watches a folder.

## Replies

I read issues daily and aim to answer within a day. If an email cannot be
parsed from what you pasted, I will say so rather than guess at it.

I am not a professional programmer — I build these with an AI assistant and run
them on my own server. So expect a straight answer about what the code does and
an honest one about what I do not know.

## License

MIT, same as the project. Opening a pull request means your change goes out
under it.
