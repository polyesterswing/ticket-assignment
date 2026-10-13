"""Coverage gaps for one week. Pure functions: no database, no clock.

Required windows and shifts are placed on the week's real dates, each in its
own timezone, and turned into UTC instants. That way every date uses its own
UTC offset, so weeks where only one of the timezones changes its clocks work
without special cases. Gaps are required time minus covered time, converted
back to company-local dates and times.

Local times that don't exist (clocks going forward) resolve to the same clock
time after the jump; local times that happen twice (clocks going back) use
the first occurrence. This is Python's zoneinfo behaviour with fold=0.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from clearfeed.domain.schedule import MINUTES_PER_DAY, Span, local_instant, shift_spans
from clearfeed.models import RequiredHours, Shift


@dataclass(frozen=True)
class Gap:
    """Uncovered required time on one company-local date. end_minute may be 1440.

    start_at/end_at are the exact UTC instants. They keep the order clear when
    clocks change during a gap, e.g. 01:45 BST to 01:15 GMT when clocks go back.
    """

    date: date
    start_minute: int
    end_minute: int
    start_at: datetime
    end_at: datetime


def week_start(day: date) -> date:
    """The Monday of the week containing `day`."""
    return day - timedelta(days=day.weekday())


def find_gaps(
    company_timezone: str,
    week_of: date,
    required: Iterable[RequiredHours],
    agents: Iterable[tuple[str, Iterable[Shift]]],
) -> list[Gap]:
    """Required time in the week starting `week_of` (a Monday) that no shift covers.

    `agents` is (timezone, shifts) per agent.
    """
    company_tz = ZoneInfo(company_timezone)

    required_spans = [
        (
            local_instant(week_of + timedelta(days=w.day_of_week), w.start_minute, company_tz),
            local_instant(week_of + timedelta(days=w.day_of_week), w.end_minute, company_tz),
        )
        for w in required
    ]

    covered: list[Span] = []
    for timezone, shifts in agents:
        agent_tz = ZoneInfo(timezone)
        for shift in shifts:
            # A few days either side of the week: agents can be ~26 hours from the
            # company timezone, and overnight shifts run into the next day.
            covered.extend(shift_spans(shift, agent_tz, week_of, range(-3, 10)))

    gaps = _subtract(_merge(required_spans), _merge(covered))
    return [piece for gap in gaps for piece in _to_local(gap, company_tz)]


def _merge(spans: list[Span]) -> list[Span]:
    """Sort and join overlapping or touching spans."""
    merged: list[Span] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _subtract(required: list[Span], covered: list[Span]) -> list[Span]:
    """Parts of `required` not in `covered`. Both sorted and merged."""
    gaps = []
    for req_start, req_end in required:
        cursor = req_start
        for cov_start, cov_end in covered:
            if cov_end <= cursor:
                continue
            if cov_start >= req_end:
                break
            if cov_start > cursor:
                gaps.append((cursor, cov_start))
            cursor = max(cursor, cov_end)
            if cursor >= req_end:
                break
        if cursor < req_end:
            gaps.append((cursor, req_end))
    return gaps


def _to_local(span: Span, tz: ZoneInfo) -> list[Gap]:
    """Split a UTC span at company-local midnights into per-date gaps."""
    pieces = []
    start, end = span
    while start < end:
        local_start = start.astimezone(tz)
        day = local_start.date()
        midnight = local_instant(day, MINUTES_PER_DAY, tz)
        piece_end = min(end, midnight)

        local_end = piece_end.astimezone(tz)
        end_minute = (
            MINUTES_PER_DAY
            if local_end.date() > day
            else local_end.hour * 60 + local_end.minute
        )
        start_minute = local_start.hour * 60 + local_start.minute
        pieces.append(Gap(day, start_minute, end_minute, start, piece_end))
        start = piece_end
    return pieces
