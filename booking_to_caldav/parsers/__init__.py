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


def all_parsers() -> list[Parser]:
    _load()
    return list(_REGISTRY)


def parse(email: Email) -> list[Segment]:
    """Return segments from the first parser that claims this email."""
    for parser in all_parsers():
        if parser.matches(email):
            return parser.parse(email)
    return []
