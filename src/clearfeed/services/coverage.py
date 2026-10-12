from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from clearfeed.domain.coverage import Gap, find_gaps, week_start
from clearfeed.models import Agent, Company, Shift
from clearfeed.services.required_hours import get_required_hours


def get_coverage(
    session: Session, company: Company, week_of: date | None, now: datetime
) -> tuple[date, list[Gap]]:
    """Gaps for the week containing `week_of`, or the current week in company time."""
    if week_of is None:
        week_of = now.astimezone(ZoneInfo(company.timezone)).date()
    monday = week_start(week_of)

    agents = session.scalars(select(Agent).where(Agent.company_id == company.id)).all()
    shifts_by_agent: dict[int, list[Shift]] = defaultdict(list)
    for shift in session.scalars(
        select(Shift).join(Agent).where(Agent.company_id == company.id)
    ):
        shifts_by_agent[shift.agent_id].append(shift)

    gaps = find_gaps(
        company.timezone,
        monday,
        get_required_hours(session, company),
        [(agent.timezone, shifts_by_agent[agent.id]) for agent in agents],
    )
    return monday, gaps
