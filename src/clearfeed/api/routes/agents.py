from fastapi import APIRouter

from clearfeed.api.deps import AgentDep, CompanyDep, SessionDep
from clearfeed.schemas import AgentOut, AgentPatch
from clearfeed.services import agents

# path ids are resolved through scoped lookups in deps.py
router = APIRouter(prefix="/companies/{company_id}/agents", tags=["agents"])


@router.get("")
def list_agents(company: CompanyDep, session: SessionDep) -> list[AgentOut]:
    return [AgentOut.model_validate(a) for a in agents.list_agents(session, company)]


@router.patch("/{agent_id}")
def update_agent(body: AgentPatch, agent: AgentDep, session: SessionDep) -> AgentOut:
    """Change the agent's timezone. Existing shifts keep their local clock times."""
    return AgentOut.model_validate(agents.update_timezone(session, agent, body.timezone))
