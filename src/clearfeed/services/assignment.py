from datetime import UTC, datetime
from typing import Any

from psycopg.errors import LockNotAvailable
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from clearfeed.core.config import get_settings
from clearfeed.core.errors import AppError
from clearfeed.domain.ranking import Candidate, rank
from clearfeed.domain.schedule import DAYS, format_hhmm, matching_shift
from clearfeed.models import Agent, AssignmentLog, Company, Shift, TicketAssignment
from clearfeed.services.agents import agents_with_shifts


def assign(session: Session, company: Company, ticket_id: str, now: datetime) -> TicketAssignment:
    """Assign a ticket, or return its stored assignment if it already has one.

    Runs under a per-company row lock, so the active counts read here can't
    change before this transaction writes and commits.
    """
    settings = get_settings()
    _lock_company(session, company, settings.assignment_lock_timeout_seconds)

    ticket = session.get(TicketAssignment, (company.id, ticket_id), populate_existing=True)
    if ticket is not None and ticket.agent_id is not None:
        session.commit()  # release the lock; nothing to write
        return ticket

    scheduled = _scheduled_agents(session, company, now)
    stats = _ticket_stats(session, [agent.id for agent, _ in scheduled])
    candidates = [Candidate(agent.id, *stats.get(agent.id, (0, None))) for agent, _ in scheduled]
    winner, reason = rank(candidates, settings.active_ticket_limit)

    if ticket is None:
        ticket = TicketAssignment(company_id=company.id, ticket_id=ticket_id)
        session.add(ticket)
    ticket.agent_id = winner.agent_id if winner else None
    ticket.reason_code = reason
    ticket.assigned_at = now if winner else None

    session.add(
        AssignmentLog(
            company_id=company.id,
            ticket_id=ticket_id,
            agent_id=ticket.agent_id,
            evaluated_at=now,
            reason_code=reason,
            snapshot=_snapshot(settings.active_ticket_limit, scheduled, candidates),
        )
    )
    session.commit()
    return ticket


def complete(
    session: Session, company: Company, ticket_id: str, now: datetime
) -> TicketAssignment:
    """Mark an assigned ticket completed. Repeats return the original completion."""
    completed = session.scalars(
        update(TicketAssignment)
        .where(
            TicketAssignment.company_id == company.id,
            TicketAssignment.ticket_id == ticket_id,
            TicketAssignment.agent_id.is_not(None),
            TicketAssignment.completed_at.is_(None),
        )
        .values(completed_at=now)
        .returning(TicketAssignment)
    ).one_or_none()
    if completed is not None:
        session.commit()
        return completed

    ticket = session.get(TicketAssignment, (company.id, ticket_id))
    if ticket is None:
        raise AppError(404, "TICKET_NOT_FOUND", f"Ticket {ticket_id} not found")
    if ticket.agent_id is None:
        raise AppError(409, "TICKET_NOT_ASSIGNED", f"Ticket {ticket_id} is not assigned")
    return ticket  # already completed


def list_log(
    session: Session,
    company: Company,
    ticket_id: str | None,
    assigned: bool | None,
    limit: int,
    cursor: int | None,
) -> tuple[list[tuple[AssignmentLog, Agent | None]], int | None]:
    """Log entries newest first, optionally only (un)assigned ones. Returns (page, next_cursor)."""
    query = (
        select(AssignmentLog, Agent)
        .outerjoin(Agent, Agent.id == AssignmentLog.agent_id)
        .where(AssignmentLog.company_id == company.id)
        .order_by(AssignmentLog.id.desc())
        .limit(limit + 1)
    )
    if ticket_id is not None:
        query = query.where(AssignmentLog.ticket_id == ticket_id)
    if assigned is True:
        query = query.where(AssignmentLog.agent_id.is_not(None))
    elif assigned is False:
        query = query.where(AssignmentLog.agent_id.is_(None))
    if cursor is not None:
        query = query.where(AssignmentLog.id < cursor)

    rows = [(entry, agent) for entry, agent in session.execute(query)]
    page = rows[:limit]
    next_cursor = page[-1][0].id if len(rows) > limit else None
    return page, next_cursor


def _lock_company(session: Session, company: Company, timeout_seconds: float) -> None:
    session.execute(text(f"SET LOCAL lock_timeout = '{int(timeout_seconds * 1000)}ms'"))
    try:
        session.execute(select(Company.id).where(Company.id == company.id).with_for_update())
    except OperationalError as exc:
        if isinstance(exc.orig, LockNotAvailable):
            session.rollback()
            raise AppError(
                503,
                "ASSIGNMENT_LOCK_TIMEOUT",
                "Another assignment for this company is in progress; retry shortly",
            ) from exc
        raise


def _scheduled_agents(
    session: Session, company: Company, now: datetime
) -> list[tuple[Agent, Shift]]:
    """Agents in a shift at `now`, with the shift they're in, ordered by id."""
    scheduled = []
    for agent, shifts in agents_with_shifts(session, company):
        shift = matching_shift(shifts, agent.timezone, now)
        if shift is not None:
            scheduled.append((agent, shift))
    return scheduled


def _ticket_stats(session: Session, agent_ids: list[int]) -> dict[int, tuple[int, datetime | None]]:
    """agent_id -> (active ticket count, latest assigned_at including completed tickets)."""
    if not agent_ids:
        return {}
    rows = session.execute(
        select(
            TicketAssignment.agent_id,
            func.count().filter(TicketAssignment.completed_at.is_(None)),
            func.max(TicketAssignment.assigned_at),
        )
        .where(TicketAssignment.agent_id.in_(agent_ids))
        .group_by(TicketAssignment.agent_id)
    )
    return {agent_id: (active, last) for agent_id, active, last in rows}


def _snapshot(
    limit: int, scheduled: list[tuple[Agent, Shift]], candidates: list[Candidate]
) -> dict[str, Any]:
    """What the decision was based on, for the assignment log."""
    return {
        "active_ticket_limit": limit,
        "scheduled_agents": [
            {
                "agent_id": agent.id,
                "active": candidate.active,
                "last_assigned_at": _iso(candidate.last_assigned_at),
                "local_tz": agent.timezone,
                "matched_shift": {
                    "day": DAYS[shift.day_of_week],
                    "start": format_hhmm(shift.start_minute),
                    "end": format_hhmm(shift.end_minute),
                },
            }
            for (agent, shift), candidate in zip(scheduled, candidates)
        ],
    }


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None
