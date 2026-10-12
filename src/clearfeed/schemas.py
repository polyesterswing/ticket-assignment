"""API request and response schemas.

These follow the JSON contract in docs/implementation.md, which differs from
the table layout (e.g. "day": "MON" instead of day_of_week 0, and "09:00"
instead of 540 minutes since midnight).
"""

import datetime as dt
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
from clearfeed.domain.schedule import DAYS, MINUTES_PER_DAY, format_hhmm, parse_hhmm

Day = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _parse_start(value: object) -> int:
    minute = parse_hhmm(value)
    if minute == MINUTES_PER_DAY:
        raise ValueError("start can't be 24:00")
    return minute


def _parse_end(value: object) -> int:
    # An end of 00:00 means midnight at the end of the day, same as 24:00.
    return parse_hhmm(value) or MINUTES_PER_DAY


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


def _to_utc(value: dt.datetime) -> dt.datetime:
    return value.astimezone(dt.UTC)


# Always rendered in UTC, e.g. "2026-10-12T09:55:00Z".
UTCDatetime = Annotated[dt.datetime, AfterValidator(_to_utc)]


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_id: int
    ticket_id: str
    agent_id: int | None
    reason_code: models.ReasonCode
    assigned_at: UTCDatetime | None
    completed_at: UTCDatetime | None


class CompletionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticket_id: str
    agent_id: int
    completed_at: UTCDatetime


Outcome = Literal["ASSIGNED", "UNASSIGNED"]


class LogAgentOut(BaseModel):
    id: int
    name: str


class LogItemOut(BaseModel):
    id: int
    ticket_id: str
    outcome: Outcome
    agent: LogAgentOut | None
    reason_code: models.ReasonCode
    evaluated_at: UTCDatetime
    snapshot: dict


class AssignmentLogOut(BaseModel):
    items: list[LogItemOut]
    next_cursor: int | None
