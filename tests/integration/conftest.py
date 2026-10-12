import os
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session

from clearfeed.api.deps import get_now
from clearfeed.app import app
from clearfeed.core.config import get_settings
from clearfeed.core.db import SessionLocal, engine
from clearfeed.models import Agent, Company, ReasonCode, Shift, TicketAssignment
from clearfeed.schemas import DAYS, parse_hhmm

ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    """Create the test database if needed and migrate it to head."""
    url = make_url(os.environ["DATABASE_URL"])
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()

    command.upgrade(Config(ROOT / "alembic.ini"), "head")


@pytest.fixture(autouse=True)
def clean_tables() -> None:
    """Empty every table before each test. Truncate rather than roll back,
    because concurrency tests need real commits visible to other connections."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE company, agent, shift, required_hours, ticket_assignment, "
                "assignment_log RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


@pytest.fixture
def make_company(session: Session) -> Callable[..., Company]:
    def make(name: str = "Acme", timezone: str = "Europe/London") -> Company:
        company = Company(name=name, timezone=timezone)
        session.add(company)
        session.commit()
        return company

    return make


@pytest.fixture
def make_agent(session: Session) -> Callable[..., Agent]:
    def make(company: Company, name: str = "Agent", timezone: str = "UTC") -> Agent:
        agent = Agent(company_id=company.id, name=name, timezone=timezone)
        session.add(agent)
        session.commit()
        return agent

    return make


@pytest.fixture
def make_shift(session: Session) -> Callable[..., Shift]:
    def make(agent: Agent, day: str, start: str, end: str) -> Shift:
        shift = Shift(
            agent_id=agent.id,
            day_of_week=DAYS.index(day),
            start_minute=parse_hhmm(start),
            end_minute=parse_hhmm(end),
        )
        session.add(shift)
        session.commit()
        return shift

    return make


@pytest.fixture
def make_ticket(session: Session) -> Callable[..., TicketAssignment]:
    """Insert an assigned ticket directly, e.g. to give an agent active tickets."""

    def make(
        agent: Agent,
        ticket_id: str,
        assigned_at: datetime,
        completed_at: datetime | None = None,
    ) -> TicketAssignment:
        ticket = TicketAssignment(
            company_id=agent.company_id,
            ticket_id=ticket_id,
            agent_id=agent.id,
            reason_code=ReasonCode.FEWEST_ACTIVE,
            assigned_at=assigned_at,
            completed_at=completed_at,
        )
        session.add(ticket)
        session.commit()
        return ticket

    return make


@pytest.fixture
def set_now() -> Iterator[Callable[[datetime], None]]:
    """Pin the API's clock to a fixed instant."""

    def pin(instant: datetime) -> None:
        app.dependency_overrides[get_now] = lambda: instant

    yield pin
    app.dependency_overrides.pop(get_now, None)


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch):
    """The app's settings; attributes set through monkeypatch are undone after the test."""

    class Setter:
        def __setattr__(self, name: str, value: object) -> None:
            monkeypatch.setattr(get_settings(), name, value)

    return Setter()
