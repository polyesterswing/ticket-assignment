from datetime import date

import pytest

from clearfeed.domain.coverage import find_gaps, week_start
from clearfeed.models import RequiredHours, Shift
from clearfeed.schemas import DAYS, format_hhmm, parse_hhmm

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI"]


def window(day: str, start: str, end: str) -> RequiredHours:
    return RequiredHours(
        day_of_week=DAYS.index(day), start_minute=parse_hhmm(start), end_minute=parse_hhmm(end)
    )


def shift(day: str, start: str, end: str) -> Shift:
    return Shift(
        day_of_week=DAYS.index(day), start_minute=parse_hhmm(start), end_minute=parse_hhmm(end)
    )


def gaps(company_tz: str, week_of: str, required, agents) -> list[tuple[str, str, str]]:
    """Gaps as (date, start, end) strings for readable assertions."""
    return [
        (g.date.isoformat(), format_hhmm(g.start_minute), format_hhmm(g.end_minute))
        for g in find_gaps(company_tz, date.fromisoformat(week_of), required, agents)
    ]


@pytest.mark.parametrize(
    ("day", "monday"),
    [("2026-10-12", "2026-10-12"), ("2026-10-14", "2026-10-12"), ("2026-10-18", "2026-10-12")],
)
def test_week_start_is_monday(day: str, monday: str) -> None:
    assert week_start(date.fromisoformat(day)) == date.fromisoformat(monday)


def test_prd_example() -> None:
    """London company, Mon-Fri 08:00-20:00. An LA agent works Mon 09:00-17:00,
    which in January is Mon 17:00 - Tue 01:00 London. Only Mon 17:00-20:00
    counts; Tue 00:00-01:00 is outside required hours."""
    required = [window(d, "08:00", "20:00") for d in WEEKDAYS]
    agents = [("America/Los_Angeles", [shift("MON", "09:00", "17:00")])]

    assert gaps("Europe/London", "2026-01-12", required, agents) == [
        ("2026-01-12", "08:00", "17:00"),
        ("2026-01-13", "08:00", "20:00"),
        ("2026-01-14", "08:00", "20:00"),
        ("2026-01-15", "08:00", "20:00"),
        ("2026-01-16", "08:00", "20:00"),
    ]


@pytest.mark.parametrize(
    ("week_of", "monday_gap"),
    [
        # London BST (UTC+1), LA PDT (UTC-7): LA 09:00 is London 17:00.
        ("2026-10-19", ("2026-10-19", "08:00", "17:00")),
        # London changed clocks on Oct 25 (now GMT), LA not until Nov 1: 16:00.
        ("2026-10-26", ("2026-10-26", "08:00", "16:00")),
    ],
)
def test_october_clock_change_weeks(week_of: str, monday_gap) -> None:
    required = [window("MON", "08:00", "20:00")]
    agents = [("America/Los_Angeles", [shift("MON", "09:00", "17:00")])]

    assert gaps("Europe/London", week_of, required, agents) == [monday_gap]


def test_sunday_overnight_from_previous_week_covers_monday_morning() -> None:
    required = [window("MON", "00:00", "08:00")]
    agents = [("UTC", [shift("SUN", "22:00", "06:00")])]

    assert gaps("UTC", "2026-10-12", required, agents) == [("2026-10-12", "06:00", "08:00")]


def test_back_to_back_shifts_from_different_agents_leave_no_gap() -> None:
    required = [window("MON", "08:00", "20:00")]
    agents = [
        ("UTC", [shift("MON", "08:00", "12:00")]),
        ("Asia/Kolkata", [shift("MON", "17:30", "01:30")]),  # 12:00-20:00 UTC
    ]

    assert gaps("UTC", "2026-10-12", required, agents) == []


def test_no_required_hours_means_no_gaps() -> None:
    assert gaps("UTC", "2026-10-12", [], []) == []


def test_adjacent_windows_give_one_gap_per_date() -> None:
    required = [
        window("MON", "08:00", "12:00"),
        window("MON", "12:00", "20:00"),
        window("MON", "20:00", "24:00"),
        window("TUE", "00:00", "04:00"),
    ]

    assert gaps("UTC", "2026-10-12", required, []) == [
        ("2026-10-12", "08:00", "24:00"),
        ("2026-10-13", "00:00", "04:00"),
    ]


def test_clocks_going_forward_nonexistent_start_moves_after_the_jump() -> None:
    """London skips 01:00-02:00 on 2026-03-29. A shift starting at 01:30 local
    starts at 01:30 UTC (02:30 BST); 04:00 BST is 03:00 UTC."""
    required = [window("SUN", "00:00", "03:00")]
    agents = [("Europe/London", [shift("SUN", "01:30", "04:00")])]

    assert gaps("UTC", "2026-03-23", required, agents) == [("2026-03-29", "00:00", "01:30")]


def test_clocks_going_back_repeated_start_uses_first_occurrence() -> None:
    """London repeats 01:00-02:00 on 2026-10-25. The first 01:30 is BST,
    00:30 UTC."""
    required = [window("SUN", "00:00", "03:00")]
    agents = [("Europe/London", [shift("SUN", "01:30", "03:00")])]

    assert gaps("UTC", "2026-10-19", required, agents) == [("2026-10-25", "00:00", "00:30")]
