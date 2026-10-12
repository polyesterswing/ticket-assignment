from datetime import date

from fastapi import APIRouter

from clearfeed.api.deps import CompanyDep, NowDep, SessionDep
from clearfeed.schemas import DAYS, CoverageOut, GapOut
from clearfeed.services import coverage

router = APIRouter(prefix="/companies/{company_id}/coverage", tags=["coverage"])


@router.get("")
def get_coverage(
    company: CompanyDep, session: SessionDep, now: NowDep, week_of: date | None = None
) -> CoverageOut:
    """Required hours with no agent scheduled, in the company timezone.

    `week_of` can be any date; the week starts on the Monday on or before it.
    Defaults to the current week in the company timezone.
    """
    monday, gaps = coverage.get_coverage(session, company, week_of, now)
    return CoverageOut(
        company_timezone=company.timezone,
        week_start=monday,
        fully_covered=not gaps,
        gaps=[
            GapOut(day=DAYS[g.date.weekday()], date=g.date, start=g.start_minute, end=g.end_minute)
            for g in gaps
        ],
    )
