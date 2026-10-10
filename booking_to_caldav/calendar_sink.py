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
                 content_type: str | None = None) -> int:
        request = urllib.request.Request(href, data=body, method=method)
        request.add_header("Authorization", self._auth)
        if content_type:
            request.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    def check(self) -> int:
        """Confirm the collection answers before writing anything to it."""
        return self._request("OPTIONS", self.url)

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
