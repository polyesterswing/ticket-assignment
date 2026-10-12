from typing import Annotated

from fastapi import APIRouter, Path

from clearfeed.api.deps import CompanyDep, NowDep, SessionDep
from clearfeed.schemas import CompletionOut, TicketOut
from clearfeed.services import assignment

# path ids are resolved through scoped lookups in deps.py
router = APIRouter(prefix="/companies/{company_id}/tickets/{ticket_id}", tags=["tickets"])

# Non-blank, with no leading or trailing whitespace.
TicketId = Annotated[str, Path(max_length=255, pattern=r"^\S(.*\S)?$")]


@router.post("/assign")
def assign_ticket(
    ticket_id: TicketId, company: CompanyDep, session: SessionDep, now: NowDep
) -> TicketOut:
    """Assign the ticket to the fairest available agent, or explain why not.

    Repeats return the stored assignment without re-evaluating. A ticket that
    was left unassigned is evaluated again.
    """
    return TicketOut.model_validate(assignment.assign(session, company, ticket_id, now))


@router.post("/complete")
def complete_ticket(
    ticket_id: TicketId, company: CompanyDep, session: SessionDep, now: NowDep
) -> CompletionOut:
    """Mark the ticket completed, freeing the agent's capacity once."""
    return CompletionOut.model_validate(assignment.complete(session, company, ticket_id, now))
