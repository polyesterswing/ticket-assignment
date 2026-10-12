from typing import Annotated

from fastapi import APIRouter, Query

from clearfeed.api.deps import CompanyDep, SessionDep
from clearfeed.schemas import AssignmentLogOut, LogAgentOut, LogItemOut, Outcome
from clearfeed.services import assignment

router = APIRouter(prefix="/companies/{company_id}/assignment-log", tags=["assignment log"])


@router.get("")
def list_assignment_log(
    company: CompanyDep,
    session: SessionDep,
    ticket_id: str | None = None,
    outcome: Outcome | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: int | None = None,
) -> AssignmentLogOut:
    """Assignment decisions, newest first. Pass next_cursor as cursor for the next page."""
    assigned = None if outcome is None else outcome == "ASSIGNED"
    page, next_cursor = assignment.list_log(session, company, ticket_id, assigned, limit, cursor)
    return AssignmentLogOut(
        items=[
            LogItemOut(
                id=entry.id,
                ticket_id=entry.ticket_id,
                outcome="ASSIGNED" if entry.agent_id is not None else "UNASSIGNED",
                agent=LogAgentOut(id=agent.id, name=agent.name) if agent else None,
                reason_code=entry.reason_code,
                evaluated_at=entry.evaluated_at,
                snapshot=entry.snapshot,
            )
            for entry, agent in page
        ],
        next_cursor=next_cursor,
    )
