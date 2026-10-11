"""Trip.com hotel confirmations, Japanese layout (JP_HTL_NoReply@trip.com).

The HTML, once de-tagged, prints the stay as:

    ホテル確認番号：K26999999999
    ホテルサンプル神戸
    電話+81-78-0000000
    予約詳細
    チェックイン
    2027年11月6日   15:00～00:00   ホテル現地時間
    チェックアウト
    2027年11月7日   12:00まで   ホテル現地時間
    所在地 〒650-0000 兵庫県神戸市中央区例町 1-2

Three differences from an airline email are worth knowing about:

* The year IS printed, so none of the weekday guessing applies here.
* The timezone is not. "ホテル現地時間" says the times are local without
  saying local to where, and there is no IATA code to fall back on. The
  address is the only handle (see core.stay_tz).
* The booking number arrives with zero-width non-joiners sprinkled through it
  — 1‌385‌436‌... — so that mail clients do not turn it into a
  phone link. Read literally it is not the number the hotel has.
"""

from __future__ import annotations

import re
from datetime import date

from ..core import TRAVEL, Stay
from . import Email, Parser, register

ZERO_WIDTH = re.compile(r"[​‌‍⁠﻿]")

JP_DATE = r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日"

CHECK_IN = re.compile(r"チェックイン\s*" + JP_DATE + r"[^\d]{0,20}(\d{1,2}):(\d{2})")
CHECK_OUT = re.compile(r"チェックアウト\s*" + JP_DATE + r"[^\d]{0,20}(\d{1,2}):(\d{2})")

BOOKING_REF = re.compile(r"予約番号[：:\s]*([0-9]{8,24})")
CONFIRMATION = re.compile(r"ホテル確認番号[：:\s]*([A-Z0-9-]{6,24})")
ADDRESS = re.compile(r"所在地\s*(〒?[^\r\n]{4,80})")
PHONE = re.compile(r"電話\s*([+0-9][0-9\-() ]{6,24})")
GUEST = re.compile(r"宿泊者姓名\s*([^\r\n]{2,60})")
GUEST_IS_PROSE = re.compile(r"^[とをはがのにで、。]")
"""The label appears twice.

Once inside a sentence — 「予約の際にご提供の 宿泊者姓名と有効な身分証明書 を
利用してチェックインしてください」 — and once as an actual field further down.
The first occurrence continues into a particle, which is how they are told
apart; taking the first match yields 「と有効な身分証明書」 as the guest's name.
"""
ROOM = re.compile(r"^\s*(【[^】]+】[^\r\n]{2,60})", re.M)
PRICE = re.compile(r"合計金額\s*(?:[^\r\n]*\r?\n)?\s*(?:前払い\s*)?([0-9,]+円)")
CANCEL_FREE = re.compile(r"キャンセル無料\s*[-–]?\s*(" + JP_DATE + r"\s*\d{1,2}:\d{2})")
MEALS = re.compile(r"食事\s*\r?\n\s*([^\r\n]{2,30})")

# The subject names the hotel, and does it without the surrounding clutter:
# "[予約確認] ホテルサンプル神戸のご予約の確認が完了しました-NoReply"
HOTEL_IN_SUBJECT = re.compile(r"(?:\[[^\]]*\]\s*)?(.+?)の(?:ご)?予約")


class TripComHotel(Parser):
    name = "Trip.com hotel, Japanese (JP_HTL_NoReply@trip.com)"

    def matches(self, message: Email) -> bool:
        if "trip.com" not in f"{message.sender}".lower():
            return False
        body = _clean(message.body)
        return bool(CHECK_IN.search(body) and CHECK_OUT.search(body))

    def parse(self, message: Email) -> list:
        body = _clean(message.body)

        check_in = CHECK_IN.search(body)
        check_out = CHECK_OUT.search(body)
        reference = BOOKING_REF.search(body)
        if not (check_in and check_out and reference):
            return []

        hotel = self._hotel(message, body)
        if not hotel:
            return []

        stay = Stay(
            hotel=hotel,
            address=_first(ADDRESS, body) or "",
            check_in=_day(check_in),
            check_out=_day(check_out),
            booking_ref=reference.group(1),
            check_in_time=f"{int(check_in.group(4)):02d}:{check_in.group(5)}",
            check_out_time=f"{int(check_out.group(4)):02d}:{check_out.group(5)}",
            guest=self._guest(body),
            room=_first(ROOM, body),
            meals=_first(MEALS, body),
            price=_first(PRICE, body),
            cancellation=self._cancellation(body),
            phone=_first(PHONE, body),
            confirmation=_first(CONFIRMATION, body),
            source=self.name,
            category=TRAVEL,
        )
        return stay.events()

    @staticmethod
    def _hotel(message: Email, body: str) -> str | None:
        from_subject = HOTEL_IN_SUBJECT.search(message.subject)
        if from_subject:
            name = from_subject.group(1).strip()
            if 2 <= len(name) <= 60:
                return name
        # Fall back to the line above the phone number, which is the hotel.
        near_phone = re.search(r"([^\r\n]{2,60})\r?\n\s*電話\s*[+0-9]", body)
        return near_phone.group(1).strip() if near_phone else None

    @staticmethod
    def _guest(body: str) -> str | None:
        for candidate in GUEST.findall(body):
            value = candidate.strip()
            if value and not GUEST_IS_PROSE.match(value):
                return value
        return None

    @staticmethod
    def _cancellation(body: str) -> str | None:
        free = CANCEL_FREE.search(body)
        if free:
            return f"free until {free.group(1)} (hotel local time)"
        return None


def _clean(body: str) -> str:
    """Drop the zero-width padding and squeeze the de-tagged whitespace.

    Spaces are collapsed but newlines are kept: several fields are identified
    by sitting on the line after their label.
    """
    body = ZERO_WIDTH.sub("", body)
    body = re.sub(r"[ \t　]+", " ", body)
    return re.sub(r"\n{3,}", "\n\n", body)


def _first(pattern: re.Pattern[str], body: str) -> str | None:
    found = pattern.search(body)
    return found.group(1).strip() if found else None


def _day(match: re.Match[str]) -> date:
    return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))


register(TripComHotel())
