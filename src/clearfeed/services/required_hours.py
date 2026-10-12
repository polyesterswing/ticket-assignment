from datetime import time

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from clearfeed.core.errors import AppError
from clearfeed.domain.schedule import find_window_overlap
from clearfeed.models import Company, RequiredHours
from clearfeed.schemas import DAYS


def get_required_hours(session: Session, company: Company) -> list[RequiredHours]:
    return list(
        session.scalars(
            select(RequiredHours)
            .where(RequiredHours.company_id == company.id)
            .order_by(RequiredHours.day_of_week, RequiredHours.start_time)
        )
    )


def replace_required_hours(
    session: Session, company: Company, windows: list[tuple[int, time, time]]
) -> list[RequiredHours]:
    """Replace the company's full set of windows (day_of_week, start, end)."""
    new = [
        RequiredHours(company_id=company.id, day_of_week=day, start_time=start, end_time=end)
        for day, start, end in windows
    ]
    overlap = find_window_overlap(new)
    if overlap is not None:
        a, b = overlap
        raise AppError(
            422,
            "REQUIRED_HOURS_OVERLAP",
            f"{_describe(a)} overlaps {_describe(b)}",
        )

    # Serialize replacements per company; otherwise two concurrent PUTs can
    # each delete the old set and leave a mix of both new sets.
    session.execute(select(Company.id).where(Company.id == company.id).with_for_update())
    session.execute(delete(RequiredHours).where(RequiredHours.company_id == company.id))
    session.add_all(new)
    session.commit()
    return get_required_hours(session, company)


def _describe(window: RequiredHours) -> str:
    return f"{DAYS[window.day_of_week]} {window.start_time:%H:%M}-{window.end_time:%H:%M}"
