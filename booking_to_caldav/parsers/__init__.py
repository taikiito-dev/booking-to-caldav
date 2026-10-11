"""Parser registry.

One parser per sender format. A parser answers two questions: does this email
look like mine, and what segments are in it. Adding support for another airline
means adding one module here and one line in `_load()` — nothing else in the
project needs to change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..core import Segment


@dataclass(frozen=True)
class Email:
    subject: str
    sender: str
    body: str
    received: date
    calendars: tuple[str, ...] = ()
    """Decoded text/calendar parts, if the email carried any.

    An invitation states its own times and timezone, so a parser that reads
    one does not have to understand the prose around it.
    """


class Parser:
    """Interface every parser implements."""

    name: str = "unnamed"

    def matches(self, email: Email) -> bool:
        raise NotImplementedError

    def parse(self, email: Email) -> list[Segment]:
        raise NotImplementedError


_REGISTRY: list[Parser] = []


def register(parser: Parser) -> Parser:
    _REGISTRY.append(parser)
    return parser


def _load() -> None:
    if _REGISTRY:
        return
    from . import ics_invitation  # noqa: F401  (registers on import)
    from . import singapore_airlines  # noqa: F401
    from . import trip_com_hotel  # noqa: F401


def all_parsers() -> list[Parser]:
    _load()
    return list(_REGISTRY)


MAX_FORWARD_DEPTH = 3
"""A forward of a forward of a forward is already unusual; stop there."""


def parse(email: Email) -> list[Segment]:
    """Return segments from the first parser that claims this email.

    If nothing claims it, the email may be a forward — a booking somebody else
    made, passed along — in which case the original is unwrapped and offered to
    the parsers again.
    """
    from .forwarded import unwrap

    current = email
    for _ in range(MAX_FORWARD_DEPTH + 1):
        for parser in all_parsers():
            if parser.matches(current):
                return parser.parse(current)
        inner = unwrap(current)
        if inner is None:
            return []
        current = inner
    return []
