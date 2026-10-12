from datetime import datetime, time
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    MetaData,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names so migrations are stable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ReasonCode(StrEnum):
    FEWEST_ACTIVE = "FEWEST_ACTIVE"
    TIE_LONGEST_SINCE_ASSIGNED = "TIE_LONGEST_SINCE_ASSIGNED"
    TIE_AGENT_ID = "TIE_AGENT_ID"
    NO_AGENT_SCHEDULED = "NO_AGENT_SCHEDULED"
    NO_AGENT_CAPACITY = "NO_AGENT_CAPACITY"


# Stored as text with a CHECK constraint rather than a native Postgres enum,
# so adding a code later is a constraint change, not an ALTER TYPE.
# The CHECK is declared explicitly (reason_code_check) because Enum's built-in
# constraint gets duplicated by Alembic autogenerate.
reason_code_type = Enum(ReasonCode, native_enum=False, create_constraint=False, length=32)


def reason_code_check() -> CheckConstraint:
    allowed = ", ".join(f"'{code.value}'" for code in ReasonCode)
    return CheckConstraint(f"reason_code IN ({allowed})", name="reason_code")


class Company(Base):
    __tablename__ = "company"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text)  # IANA name, e.g. Europe/London


class Agent(Base):
    __tablename__ = "agent"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"), index=True)
    name: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Shift(Base):
    """Recurring weekly shift in the agent's local time.

    day_of_week is 0=MON .. 6=SUN. end_time < start_time is an overnight shift:
    it belongs to day_of_week and ends on the following day.
    """

    __tablename__ = "shift"
    __table_args__ = (
        # Overlaps, including across days, are checked in the app.
        UniqueConstraint("agent_id", "day_of_week", "start_time"),
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="day_of_week"),
        CheckConstraint("start_time <> end_time", name="non_empty"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agent.id"))
    day_of_week: Mapped[int] = mapped_column(SmallInteger)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RequiredHours(Base):
    """Coverage window in the company timezone. No overnight windows."""

    __tablename__ = "required_hours"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="day_of_week"),
        CheckConstraint("start_time < end_time", name="start_before_end"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"), index=True)
    day_of_week: Mapped[int] = mapped_column(SmallInteger)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)


class TicketAssignment(Base):
    """Current state of a ticket. agent_id NULL means unassigned (see reason_code)."""

    __tablename__ = "ticket_assignment"
    __table_args__ = (
        reason_code_check(),
        CheckConstraint(
            "completed_at IS NULL OR agent_id IS NOT NULL",
            name="completed_requires_agent",
        ),
        # Active ticket count per agent.
        Index(
            "ix_ticket_assignment_active_agent_id",
            "agent_id",
            postgresql_where=text("completed_at IS NULL"),
        ),
        # MAX(assigned_at) per agent for the tie-break.
        Index("ix_ticket_assignment_agent_id_assigned_at", "agent_id", "assigned_at"),
    )

    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agent.id"))
    reason_code: Mapped[ReasonCode] = mapped_column(reason_code_type)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AssignmentLog(Base):
    """One row per assignment evaluation, including unassigned outcomes."""

    __tablename__ = "assignment_log"
    __table_args__ = (
        reason_code_check(),
        # Newest-first cursor pagination per company (id is the cursor).
        Index("ix_assignment_log_company_id_id", "company_id", "id"),
        Index("ix_assignment_log_company_id_ticket_id", "company_id", "ticket_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"))
    ticket_id: Mapped[str] = mapped_column(String(255))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agent.id"))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason_code: Mapped[ReasonCode] = mapped_column(reason_code_type)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
