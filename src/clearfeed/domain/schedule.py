"""
A shift is placed on a week of minutes in the agent's local time, starting
Monday 00:00 (0) and ending before the next Monday 00:00 (10080). Intervals are
start-inclusive, end-exclusive. An overnight shift (end < start) belongs to its
start day and runs into the next day; a Sunday overnight shift wraps to Monday.
"""

from collections.abc import Iterable
from datetime import datetime, time
from zoneinfo import ZoneInfo

from clearfeed.models import RequiredHours, Shift

MINUTES_PER_DAY = 24 * 60
MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY

Interval = tuple[int, int]


def _minute_of_day(t: time) -> int:
    return t.hour * 60 + t.minute


def shift_intervals(shift: Shift) -> list[Interval]:
    """Minute-of-week intervals covered by a shift; two if it wraps past Sunday."""
    start = shift.day_of_week * MINUTES_PER_DAY + _minute_of_day(shift.start_time)
    length = (_minute_of_day(shift.end_time) - _minute_of_day(shift.start_time)) % MINUTES_PER_DAY
    if length == 0:
        raise ValueError("shift start and end must differ")

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
    ordered = sorted(windows, key=lambda w: (w.day_of_week, w.start_time))
    for prev, cur in zip(ordered, ordered[1:]):
        if prev.day_of_week == cur.day_of_week and cur.start_time < prev.end_time:
            return prev, cur
    return None


def matching_shift(agent_shifts: Iterable[Shift], timezone: str, now: datetime) -> Shift | None:
    """The shift containing `now` in the agent's local time, or None.

    `agent_shifts` are one agent's shifts; `timezone` is that agent's timezone.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    local = now.astimezone(ZoneInfo(timezone))
    minute = local.weekday() * MINUTES_PER_DAY + local.hour * 60 + local.minute
    for shift in agent_shifts:
        if any(start <= minute < end for start, end in shift_intervals(shift)):
            return shift
    return None
