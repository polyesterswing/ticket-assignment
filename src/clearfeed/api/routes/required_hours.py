from fastapi import APIRouter

from clearfeed.api.deps import CompanyDep, SessionDep
from clearfeed.schemas import DAYS, RequiredHoursIn, RequiredHoursOut, required_hours_out
from clearfeed.services import required_hours

router = APIRouter(prefix="/companies/{company_id}/required-hours", tags=["required hours"])


@router.get("")
def get_required_hours(company: CompanyDep, session: SessionDep) -> RequiredHoursOut:
    """Windows in the company timezone, sorted by day, then start."""
    return required_hours_out(required_hours.get_required_hours(session, company))


@router.put("")
def replace_required_hours(
    body: RequiredHoursIn, company: CompanyDep, session: SessionDep
) -> RequiredHoursOut:
    """Replace the full set of windows. An empty list clears them."""
    windows = [(DAYS.index(w.day), w.start, w.end) for w in body.windows]
    return required_hours_out(required_hours.replace_required_hours(session, company, windows))
