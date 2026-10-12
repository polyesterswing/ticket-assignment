from fastapi import APIRouter, Response

from clearfeed.api.deps import AgentDep, SessionDep, ShiftDep
from clearfeed.domain.schedule import DAYS
from clearfeed.schemas import ShiftIn, ShiftOut, shift_out
from clearfeed.services import shifts

# path id's are resolved through scoped lookups in deps.py
router = APIRouter(prefix="/companies/{company_id}/agents/{agent_id}/shifts", tags=["shifts"])


@router.get("")
def list_shifts(agent: AgentDep, session: SessionDep) -> list[ShiftOut]:
    """The agent's shifts, sorted by day, then start."""
    return [shift_out(s) for s in shifts.list_shifts(session, agent)]


@router.post("", status_code=201)
def create_shift(body: ShiftIn, agent: AgentDep, session: SessionDep) -> ShiftOut:
    shift = shifts.create_shift(session, agent, DAYS.index(body.day), body.start, body.end)
    return shift_out(shift)


@router.put("/{shift_id}")
def replace_shift(
    body: ShiftIn, shift: ShiftDep, agent: AgentDep, session: SessionDep
) -> ShiftOut:
    shift = shifts.replace_shift(
        session, agent, shift, DAYS.index(body.day), body.start, body.end
    )
    return shift_out(shift)


@router.delete("/{shift_id}", status_code=204)
def delete_shift(shift: ShiftDep, session: SessionDep) -> Response:
    shifts.delete_shift(session, shift)
    return Response(status_code=204)
