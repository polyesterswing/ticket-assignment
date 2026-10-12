from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from clearfeed.models import Agent, Company, Shift


def list_companies(session: Session) -> list[Company]:
    return list(session.scalars(select(Company).order_by(Company.id)))


def list_agents(session: Session, company: Company) -> list[Agent]:
    return list(
        session.scalars(select(Agent).where(Agent.company_id == company.id).order_by(Agent.id))
    )


def agents_with_shifts(session: Session, company: Company) -> list[tuple[Agent, list[Shift]]]:
    """The company's agents ordered by id, each with all of their shifts."""
    shifts_by_agent: dict[int, list[Shift]] = defaultdict(list)
    for shift in session.scalars(select(Shift).join(Agent).where(Agent.company_id == company.id)):
        shifts_by_agent[shift.agent_id].append(shift)
    return [(agent, shifts_by_agent[agent.id]) for agent in list_agents(session, company)]


def update_timezone(session: Session, agent: Agent, timezone: str) -> Agent:
    """Change the agent's timezone. Shifts keep their local clock times."""
    agent.timezone = timezone
    session.commit()
    return agent
