"""API request and response schemas.

These follow the JSON contract in docs/implementation.md, which differs from
the table layout (e.g. "day": "MON" instead of day_of_week 0).
"""

from datetime import time
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, PlainSerializer, model_validator

from clearfeed import models

Day = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
DAYS: tuple[Day, ...] = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _whole_minutes(t: time) -> time:
    if t.second or t.microsecond:
        raise ValueError("time must be in whole minutes (HH:MM)")
    return t


# Accepts "22:00", serializes as "22:00" (not "22:00:00").
HHMM = Annotated[
    time,
    AfterValidator(_whole_minutes),
    PlainSerializer(lambda t: t.strftime("%H:%M"), return_type=str),
]


class ShiftIn(BaseModel):
    """Body for creating (POST) or replacing (PUT) a shift. end < start is overnight."""

    day: Day
    start: HHMM
    end: HHMM

    @model_validator(mode="after")
    def _non_empty(self) -> Self:
        if self.start == self.end:
            raise ValueError("start and end must differ")
        return self


class ShiftOut(ShiftIn):
    id: int


def shift_out(shift: models.Shift) -> ShiftOut:
    return ShiftOut(
        id=shift.id,
        day=DAYS[shift.day_of_week],
        start=shift.start_time,
        end=shift.end_time,
    )


class Window(BaseModel):
    """A required-hours window in company time. No overnight windows."""

    day: Day
    start: HHMM
    end: HHMM

    @model_validator(mode="after")
    def _start_before_end(self) -> Self:
        if self.start >= self.end:
            raise ValueError("start must be before end (overnight windows are not allowed)")
        return self


class RequiredHoursIn(BaseModel):
    windows: list[Window]


# Responses have the same shape as the PUT body.
RequiredHoursOut = RequiredHoursIn


def required_hours_out(rows: list[models.RequiredHours]) -> RequiredHoursOut:
    return RequiredHoursOut(
        windows=[
            Window(day=DAYS[r.day_of_week], start=r.start_time, end=r.end_time) for r in rows
        ]
    )
