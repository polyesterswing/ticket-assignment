from sqlalchemy import select
from sqlalchemy.orm import Session

from clearfeed.core.errors import AppError
from clearfeed.domain.schedule import DAYS, find_overlap, format_hhmm
from clearfeed.models import Agent, Shift


def list_shifts(session: Session, agent: Agent) -> list[Shift]:
    return list(
        session.scalars(
            select(Shift)
            .where(Shift.agent_id == agent.id)
            .order_by(Shift.day_of_week, Shift.start_minute)
        )
    )


def create_shift(
    session: Session, agent: Agent, day_of_week: int, start: int, end: int
) -> Shift:
    existing = _lock_agent_shifts(session, agent)
    shift = Shift(agent_id=agent.id, day_of_week=day_of_week, start_minute=start, end_minute=end)
    _reject_overlap(shift, existing)

    session.add(shift)
    session.commit()
    return shift


def replace_shift(
    session: Session, agent: Agent, shift: Shift, day_of_week: int, start: int, end: int
) -> Shift:
    others = [s for s in _lock_agent_shifts(session, agent) if s.id != shift.id]
    candidate = Shift(day_of_week=day_of_week, start_minute=start, end_minute=end)
    _reject_overlap(candidate, others)

    shift.day_of_week = day_of_week
    shift.start_minute = start
    shift.end_minute = end
    session.commit()
    return shift


def delete_shift(session: Session, shift: Shift) -> None:
    session.delete(shift)
    session.commit()


def _lock_agent_shifts(session: Session, agent: Agent) -> list[Shift]:
    """Lock the agent row, then load their shifts.

    Concurrent writes for the same agent wait here, so two requests can't both
    pass the overlap check and save overlapping shifts.
    """
    session.execute(select(Agent.id).where(Agent.id == agent.id).with_for_update())
    return list(session.scalars(select(Shift).where(Shift.agent_id == agent.id)))


def _reject_overlap(candidate: Shift, existing: list[Shift]) -> None:
    conflict = find_overlap(candidate, existing)
    if conflict is not None:
        raise AppError(
            422,
            "SHIFT_OVERLAP",
            f"Overlaps shift {conflict.id} ({DAYS[conflict.day_of_week]} "
            f"{format_hhmm(conflict.start_minute)}-{format_hhmm(conflict.end_minute)})",
        )
