from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from clearfeed.core.db import get_session
from clearfeed.core.errors import AppError
from clearfeed.models import Agent, Company, Shift

SessionDep = Annotated[Session, Depends(get_session)]


def get_company(company_id: int, session: SessionDep) -> Company:
    company = session.get(Company, company_id)
    if company is None:
        raise AppError(404, "COMPANY_NOT_FOUND", f"Company {company_id} not found")
    return company


CompanyDep = Annotated[Company, Depends(get_company)]


def get_agent(agent_id: int, company: CompanyDep, session: SessionDep) -> Agent:
    agent = session.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.company_id == company.id)
    )
    if agent is None:
        raise AppError(404, "AGENT_NOT_FOUND", f"Agent {agent_id} not found")
    return agent


AgentDep = Annotated[Agent, Depends(get_agent)]


def get_shift(shift_id: int, agent: AgentDep, session: SessionDep) -> Shift:
    shift = session.scalar(
        select(Shift).where(Shift.id == shift_id, Shift.agent_id == agent.id)
    )
    if shift is None:
        raise AppError(404, "SHIFT_NOT_FOUND", f"Shift {shift_id} not found")
    return shift


ShiftDep = Annotated[Shift, Depends(get_shift)]
