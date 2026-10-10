"""CalDAV sink.

One HTTP PUT per event, keyed on the segment's stable UID, so running the
importer twice updates the same event instead of creating a second one.
Standard library only — no CalDAV client dependency.
"""

from __future__ import annotations

import base64
import urllib.error
import urllib.request
from dataclasses import dataclass


USER_AGENT = "booking-to-caldav/0.1 (+https://github.com/taikiito-dev/booking-to-caldav)"
"""Identify the client by name.

urllib's default (`Python-urllib/3.x`) is a common blocklist entry for WAFs and
reverse proxies. When one is in front of the calendar the symptom is a 403 on
every method, including PROPFIND, while the same request from curl succeeds —
which reads like a credentials or URL problem and is neither.
"""


@dataclass(frozen=True)
class PutResult:
    uid: str
    status: int

    @property
    def created(self) -> bool:
        return self.status == 201

    @property
    def updated(self) -> bool:
        return self.status in (200, 204)

    @property
    def ok(self) -> bool:
        return self.created or self.updated


class Calendar:
    def __init__(self, url: str, username: str, password: str, timeout: int = 20):
        self.url = url.rstrip("/") + "/"
        self.timeout = timeout
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._auth = f"Basic {token}"

    def _request(self, method: str, href: str, body: bytes | None = None,
                 content_type: str | None = None,
                 headers: dict[str, str] | None = None) -> int:
        request = urllib.request.Request(href, data=body, method=method)
        request.add_header("Authorization", self._auth)
        request.add_header("User-Agent", USER_AGENT)
        if content_type:
            request.add_header("Content-Type", content_type)
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    def check(self) -> int:
        """Confirm the collection answers before writing anything to it.

        PROPFIND rather than OPTIONS: a reverse proxy in front of the calendar
        may answer OPTIONS with 403 while PUT works perfectly well, so OPTIONS
        is not a usable liveness test. A healthy collection answers 207.
        """
        body = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b'<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/>'
            b"</d:prop></d:propfind>"
        )
        return self._request(
            "PROPFIND",
            self.url,
            body=body,
            content_type="application/xml; charset=utf-8",
            headers={"Depth": "0"},
        )

    def put(self, uid: str, ics: str) -> PutResult:
        status = self._request(
            "PUT",
            f"{self.url}{uid}.ics",
            body=ics.encode("utf-8"),
            content_type="text/calendar; charset=utf-8",
        )
        return PutResult(uid=uid, status=status)

    def delete(self, uid: str) -> int:
        return self._request("DELETE", f"{self.url}{uid}.ics")
