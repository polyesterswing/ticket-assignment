"""
A shift is placed on a week of minutes in the agent's local time, starting
Monday 00:00 (0) and ending before the next Monday 00:00 (10080). Intervals are
start-inclusive, end-exclusive. An overnight shift (end < start) belongs to its
start day and runs into the next day; a Sunday overnight shift wraps to Monday.
"""

import re
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from clearfeed.models import RequiredHours, Shift

DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")  # index = day_of_week
MINUTES_PER_DAY = 24 * 60  # also "24:00", the end of a day
MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY

Interval = tuple[int, int]
Span = tuple[datetime, datetime]  # UTC instants, start inclusive, end exclusive

_HHMM = re.compile(r"(\d{2}):(\d{2})")


def parse_hhmm(value: object) -> int:
    """"HH:MM" (00:00..24:00) to minutes since midnight."""
    match = _HHMM.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError("time must be a string in HH:MM format")
    hours, minutes = int(match[1]), int(match[2])
    if minutes > 59 or hours > 24 or (hours == 24 and minutes):
        raise ValueError("time must be between 00:00 and 24:00")
    return hours * 60 + minutes


def format_hhmm(minute: int) -> str:
    """Minutes since midnight to "HH:MM"; 1440 is "24:00"."""
    return f"{minute // 60:02d}:{minute % 60:02d}"


def shift_intervals(shift: Shift) -> list[Interval]:
    """Minute-of-week intervals covered by a shift; two if it wraps past Sunday."""
    if shift.start_minute == shift.end_minute:
        raise ValueError("shift start and end must differ")
    length = shift.end_minute - shift.start_minute
    if length < 0:  # overnight
        length += MINUTES_PER_DAY

    start = shift.day_of_week * MINUTES_PER_DAY + shift.start_minute
    end = start + length
    if end <= MINUTES_PER_WEEK:
        return [(start, end)]
    return [(start, MINUTES_PER_WEEK), (0, end - MINUTES_PER_WEEK)]


def find_overlap(candidate: Shift, existing: Iterable[Shift]) -> Shift | None:
    """First existing shift that overlaps the candidate, or None.

    When replacing a shift, leave the shift being replaced out of `existing`.
    """
    candidate_intervals = shift_intervals(candidate)
    for other in existing:
        for a_start, a_end in candidate_intervals:
            for b_start, b_end in shift_intervals(other):
                if a_start < b_end and b_start < a_end:
                    return other
    return None


def find_window_overlap(
    windows: Iterable[RequiredHours],
) -> tuple[RequiredHours, RequiredHours] | None:
    """First pair of overlapping required-hours windows, or None.

    Windows never cross midnight, so sorting by (day, start) and comparing
    neighbours is enough. Back-to-back windows don't overlap.
    """
    ordered = sorted(windows, key=lambda w: (w.day_of_week, w.start_minute))
    for prev, cur in zip(ordered, ordered[1:]):
        if prev.day_of_week == cur.day_of_week and cur.start_minute < prev.end_minute:
            return prev, cur
    return None


def local_instant(day: date, minute: int, tz: ZoneInfo) -> datetime:
    """UTC instant of a local date and minute since midnight (1440 = next midnight).

    On clock-change days, a local time that doesn't exist resolves to the same
    clock time after the jump, and one that happens twice uses the first
    occurrence (zoneinfo's fold=0).
    """
    local = datetime(day.year, day.month, day.day, tzinfo=tz) + timedelta(minutes=minute)
    return local.astimezone(UTC)


def shift_spans(shift: Shift, tz: ZoneInfo, around: date, days: range) -> list[Span]:
    """UTC spans of the shift's occurrences on the dates `around + d` for d in `days`.

    A shift occurrence is one continuous span from its start instant to its end
    instant. Coverage and assignment both use this, so they always agree on when
    an agent is available, including on clock-change days.
    """
    end_minute = shift.end_minute
    if end_minute <= shift.start_minute:  # overnight
        end_minute += MINUTES_PER_DAY

    spans = []
    for offset in days:
        day = around + timedelta(days=offset)
        if day.weekday() == shift.day_of_week:
            spans.append(
                (local_instant(day, shift.start_minute, tz), local_instant(day, end_minute, tz))
            )
    return spans


def matching_shift(agent_shifts: Iterable[Shift], timezone: str, now: datetime) -> Shift | None:
    """The shift the agent is working at `now`, or None.

    `agent_shifts` are one agent's shifts; `timezone` is that agent's timezone.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    tz = ZoneInfo(timezone)
    today = now.astimezone(tz).date()
    for shift in agent_shifts:
        # Yesterday's occurrence covers overnight shifts still running today.
        spans = shift_spans(shift, tz, today, range(-1, 1))
        if any(start <= now < end for start, end in spans):
            return shift
    return None
