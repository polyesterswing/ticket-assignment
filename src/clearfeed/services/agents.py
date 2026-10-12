from sqlalchemy import select
from sqlalchemy.orm import Session

from clearfeed.models import Agent, Company


def list_companies(session: Session) -> list[Company]:
    return list(session.scalars(select(Company).order_by(Company.id)))


def list_agents(session: Session, company: Company) -> list[Agent]:
    return list(
        session.scalars(select(Agent).where(Agent.company_id == company.id).order_by(Agent.id))
    )


def update_timezone(session: Session, agent: Agent, timezone: str) -> Agent:
    """Change the agent's timezone. Shifts keep their local clock times."""
    agent.timezone = timezone
    session.commit()
    return agent
