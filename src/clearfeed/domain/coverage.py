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
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from clearfeed.domain.schedule import MINUTES_PER_DAY
from clearfeed.models import RequiredHours, Shift

Span = tuple[datetime, datetime]  # UTC instants, start inclusive, end exclusive


@dataclass(frozen=True)
class Gap:
    """Uncovered required time on one company-local date. end_minute may be 1440."""

    date: date
    start_minute: int
    end_minute: int


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
            _instant(week_of + timedelta(days=w.day_of_week), w.start_minute, company_tz),
            _instant(week_of + timedelta(days=w.day_of_week), w.end_minute, company_tz),
        )
        for w in required
    ]

    covered: list[Span] = []
    for timezone, shifts in agents:
        agent_tz = ZoneInfo(timezone)
        for shift in shifts:
            covered.extend(_shift_spans(shift, agent_tz, week_of))

    gaps = _subtract(_merge(required_spans), _merge(covered))
    return [piece for gap in gaps for piece in _to_local(gap, company_tz)]


def _instant(day: date, minute: int, tz: ZoneInfo) -> datetime:
    """UTC instant of a local date and minute since midnight (1440 = next midnight)."""
    local = datetime(day.year, day.month, day.day, tzinfo=tz) + timedelta(minutes=minute)
    return local.astimezone(UTC)


def _shift_spans(shift: Shift, tz: ZoneInfo, week_of: date) -> list[Span]:
    """Occurrences of a weekly shift around the given week, as UTC spans.

    Dates a few days either side of the week are included: agents can be up
    to ~26 hours away from the company timezone, and overnight shifts run
    into the next day.
    """
    end_minute = shift.end_minute
    if end_minute <= shift.start_minute:  # overnight
        end_minute += MINUTES_PER_DAY

    spans = []
    for offset in range(-3, 10):
        day = week_of + timedelta(days=offset)
        if day.weekday() == shift.day_of_week:
            spans.append((_instant(day, shift.start_minute, tz), _instant(day, end_minute, tz)))
    return spans


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
        midnight = _instant(day, MINUTES_PER_DAY, tz)
        piece_end = min(end, midnight)

        local_end = piece_end.astimezone(tz)
        end_minute = (
            MINUTES_PER_DAY
            if local_end.date() > day
            else local_end.hour * 60 + local_end.minute
        )
        pieces.append(Gap(day, local_start.hour * 60 + local_start.minute, end_minute))
        start = piece_end
    return pieces
