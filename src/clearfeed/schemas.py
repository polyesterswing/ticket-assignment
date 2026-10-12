"""API request and response schemas.

These follow the JSON contract in docs/implementation.md, which differs from
the table layout (e.g. "day": "MON" instead of day_of_week 0, and "09:00"
instead of 540 minutes since midnight).
"""

import datetime as dt
import re
from typing import Annotated, Literal, Self
from zoneinfo import available_timezones

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    PlainSerializer,
    WithJsonSchema,
    model_validator,
)

from clearfeed import models

Day = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
DAYS: tuple[Day, ...] = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

END_OF_DAY = 24 * 60  # 1440, written "24:00"

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


def _parse_start(value: object) -> int:
    minute = parse_hhmm(value)
    if minute == END_OF_DAY:
        raise ValueError("start can't be 24:00")
    return minute


def _parse_end(value: object) -> int:
    # An end of 00:00 means midnight at the end of the day, same as 24:00.
    return parse_hhmm(value) or END_OF_DAY


# Minutes since midnight, written as "HH:MM" in JSON.
Minute = Annotated[
    int,
    PlainSerializer(format_hhmm, return_type=str),
    WithJsonSchema({"type": "string", "pattern": r"^\d{2}:\d{2}$", "examples": ["09:00"]}),
]
StartMinute = Annotated[Minute, BeforeValidator(_parse_start)]
EndMinute = Annotated[Minute, BeforeValidator(_parse_end)]  # "24:00" or "00:00" = 1440


class ShiftIn(BaseModel):
    """Body for creating (POST) or replacing (PUT) a shift. end < start is overnight."""

    day: Day
    start: StartMinute
    end: EndMinute

    @model_validator(mode="after")
    def _non_empty(self) -> Self:
        if self.start == self.end:
            raise ValueError("start and end must differ")
        return self


class ShiftOut(BaseModel):
    id: int
    day: Day
    start: Minute
    end: Minute


def shift_out(shift: models.Shift) -> ShiftOut:
    return ShiftOut(
        id=shift.id,
        day=DAYS[shift.day_of_week],
        start=shift.start_minute,
        end=shift.end_minute,
    )


class WindowIn(BaseModel):
    """A required-hours window in company time. No overnight windows."""

    day: Day
    start: StartMinute
    end: EndMinute

    @model_validator(mode="after")
    def _start_before_end(self) -> Self:
        if self.start >= self.end:
            raise ValueError("start must be before end (overnight windows are not allowed)")
        return self


class WindowOut(BaseModel):
    day: Day
    start: Minute
    end: Minute


class RequiredHoursIn(BaseModel):
    windows: list[WindowIn]


class RequiredHoursOut(BaseModel):
    windows: list[WindowOut]


def required_hours_out(rows: list[models.RequiredHours]) -> RequiredHoursOut:
    return RequiredHoursOut(
        windows=[
            WindowOut(day=DAYS[r.day_of_week], start=r.start_minute, end=r.end_minute)
            for r in rows
        ]
    )


class GapOut(BaseModel):
    day: Day
    date: dt.date
    start: Minute
    end: Minute


class CoverageOut(BaseModel):
    company_timezone: str
    week_start: dt.date
    fully_covered: bool
    gaps: list[GapOut]


_TIMEZONES = available_timezones()


def _valid_timezone(value: str) -> str:
    if value not in _TIMEZONES:
        raise ValueError("must be an IANA timezone name, e.g. Europe/London")
    return value


Timezone = Annotated[str, AfterValidator(_valid_timezone)]


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    timezone: str


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    name: str
    timezone: str
    updated_at: dt.datetime


class AgentPatch(BaseModel):
    timezone: Timezone
