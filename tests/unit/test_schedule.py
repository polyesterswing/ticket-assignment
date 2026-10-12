from datetime import UTC, datetime

import pytest

from clearfeed.models import Shift
from clearfeed.schemas import parse_hhmm
from clearfeed.domain.schedule import find_overlap, matching_shift, shift_intervals

DAYS = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}


def shift(day: str, start: str, end: str) -> Shift:
    return Shift(
        day_of_week=DAYS[day],
        start_minute=parse_hhmm(start),
        end_minute=parse_hhmm(end),
    )


def utc(iso: str) -> datetime:
    """2026-10-12 is a Monday."""
    return datetime.fromisoformat(iso).replace(tzinfo=UTC)


# --- shift_intervals ---


def test_overnight_shift_extends_into_next_day() -> None:
    assert shift_intervals(shift("MON", "22:00", "06:00")) == [(1320, 1800)]


def test_sunday_overnight_shift_wraps_to_monday() -> None:
    assert shift_intervals(shift("SUN", "22:00", "06:00")) == [(9960, 10080), (0, 360)]


@pytest.mark.parametrize(
    ("s", "intervals"),
    [
        (shift("MON", "22:00", "24:00"), [(1320, 1440)]),
        (shift("SUN", "22:00", "24:00"), [(9960, 10080)]),  # ends exactly at week end
        (shift("TUE", "00:00", "24:00"), [(1440, 2880)]),  # whole day
    ],
)
def test_shift_ending_at_midnight(s: Shift, intervals: list[tuple[int, int]]) -> None:
    assert shift_intervals(s) == intervals


def test_empty_shift_rejected() -> None:
    with pytest.raises(ValueError):
        shift_intervals(shift("MON", "09:00", "09:00"))


# --- matching_shift ---


@pytest.mark.parametrize(
    ("s", "now", "expected"),
    [
        # Start inclusive, end exclusive.
        (shift("MON", "09:00", "17:00"), "2026-10-12T09:00:00", True),
        (shift("MON", "09:00", "17:00"), "2026-10-12T16:59:59", True),
        (shift("MON", "09:00", "17:00"), "2026-10-12T17:00:00", False),
        (shift("MON", "09:00", "17:00"), "2026-10-12T08:59:59", False),
        # Overnight shift belongs to Monday and ends Tuesday.
        (shift("MON", "22:00", "06:00"), "2026-10-12T22:00:00", True),
        (shift("MON", "22:00", "06:00"), "2026-10-13T05:59:00", True),
        (shift("MON", "22:00", "06:00"), "2026-10-13T06:00:00", False),
        (shift("MON", "22:00", "06:00"), "2026-10-12T05:59:00", False),
        # Sunday overnight wraps into Monday morning.
        (shift("SUN", "22:00", "06:00"), "2026-10-12T05:59:00", True),
        (shift("SUN", "22:00", "06:00"), "2026-10-12T06:00:00", False),
        (shift("SUN", "22:00", "06:00"), "2026-10-18T23:00:00", True),
    ],
)
def test_matching_shift_boundaries(s: Shift, now: str, expected: bool) -> None:
    assert (matching_shift([s], "UTC", utc(now)) is s) is expected


def test_matching_shift_uses_agent_timezone() -> None:
    shifts = [shift("MON", "09:00", "17:00")]
    now = utc("2026-10-12T04:00:00")  # 09:30 in Kolkata, 05:00 in London (BST)

    assert matching_shift(shifts, "Asia/Kolkata", now) is shifts[0]
    assert matching_shift(shifts, "Europe/London", now) is None


def test_matching_shift_returns_the_matching_one() -> None:
    morning = shift("MON", "06:00", "10:00")
    evening = shift("MON", "18:00", "22:00")

    assert matching_shift([morning, evening], "UTC", utc("2026-10-12T19:00:00")) is evening


def test_matching_shift_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        matching_shift([shift("MON", "09:00", "17:00")], "UTC", datetime(2026, 10, 12, 10))


# --- find_overlap ---


@pytest.mark.parametrize(
    ("a", "b", "overlaps"),
    [
        (shift("MON", "09:00", "17:00"), shift("MON", "12:00", "20:00"), True),
        (shift("MON", "09:00", "17:00"), shift("MON", "10:00", "11:00"), True),
        # Back-to-back is allowed.
        (shift("MON", "08:00", "12:00"), shift("MON", "12:00", "20:00"), False),
        # Overnight shift running into the next day's shift.
        (shift("MON", "22:00", "06:00"), shift("TUE", "05:00", "08:00"), True),
        (shift("MON", "22:00", "06:00"), shift("TUE", "06:00", "08:00"), False),
        (shift("MON", "22:00", "06:00"), shift("TUE", "22:00", "06:00"), False),
        # Sunday overnight wrapping into Monday morning.
        (shift("SUN", "22:00", "06:00"), shift("MON", "05:00", "08:00"), True),
        (shift("SUN", "22:00", "06:00"), shift("MON", "06:00", "08:00"), False),
        # Ending at 24:00 meets, but doesn't overlap, the next day's 00:00 start.
        (shift("MON", "22:00", "24:00"), shift("TUE", "00:00", "06:00"), False),
        (shift("SUN", "22:00", "24:00"), shift("MON", "00:00", "06:00"), False),
        (shift("MON", "22:00", "24:00"), shift("MON", "23:00", "02:00"), True),
        (shift("MON", "09:00", "17:00"), shift("TUE", "09:00", "17:00"), False),
    ],
)
def test_find_overlap(a: Shift, b: Shift, overlaps: bool) -> None:
    # Symmetric: order of candidate and existing doesn't matter.
    assert (find_overlap(a, [b]) is b) is overlaps
    assert (find_overlap(b, [a]) is a) is overlaps


def test_find_overlap_returns_conflicting_shift() -> None:
    existing = [shift("MON", "06:00", "08:00"), shift("MON", "12:00", "14:00")]

    assert find_overlap(shift("MON", "13:00", "15:00"), existing) is existing[1]
