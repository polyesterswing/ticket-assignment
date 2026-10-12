from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from clearfeed.domain.coverage import Gap, find_gaps, week_start
from clearfeed.models import Company
from clearfeed.services.agents import agents_with_shifts
from clearfeed.services.required_hours import get_required_hours


def get_coverage(
    session: Session, company: Company, week_of: date | None, now: datetime
) -> tuple[date, list[Gap]]:
    """Gaps for the week containing `week_of`, or the current week in company time."""
    if week_of is None:
        week_of = now.astimezone(ZoneInfo(company.timezone)).date()
    monday = week_start(week_of)

    gaps = find_gaps(
        company.timezone,
        monday,
        get_required_hours(session, company),
        [(agent.timezone, shifts) for agent, shifts in agents_with_shifts(session, company)],
    )
    return monday, gaps
