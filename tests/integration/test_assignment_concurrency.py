"""Concurrent assignment (test plan #13-#14)."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from clearfeed.app import app
from clearfeed.core.db import engine
from clearfeed.models import Agent, AssignmentLog, Company, TicketAssignment

NOW = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)  # Monday


@pytest.fixture(autouse=True)
def pinned_clock(set_now) -> None:
    set_now(NOW)


@pytest.fixture
def company(make_company) -> Company:
    return make_company(timezone="UTC")


@pytest.fixture
def agent(company, make_agent, make_shift) -> Agent:
    agent = make_agent(company, timezone="UTC")
    make_shift(agent, "MON", "09:00", "17:00")
    return agent


def in_parallel(calls: list[Callable[[TestClient], dict]]) -> list[dict]:
    """Run the calls at the same moment, each with its own client.

    Threads share the GIL, but release it while waiting on Postgres, and each
    request has its own connection, so the transactions really do interleave.
    """
    barrier = Barrier(len(calls))

    def run(call: Callable[[TestClient], dict]) -> dict:
        with TestClient(app) as client:
            barrier.wait()
            return call(client)

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(run, calls))


def assign_call(company: Company, ticket_id: str) -> Callable[[TestClient], dict]:
    def call(client: TestClient) -> dict:
        response = client.post(f"/companies/{company.id}/tickets/{ticket_id}/assign")
        assert response.status_code == 200, response.text
        return response.json()

    return call


def count(session: Session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_parallel_requests_for_one_ticket(session: Session, company, agent) -> None:
    """#13: 10 parallel /assign calls for one new ticket all get the same
    answer; one row, one log entry, one active ticket."""
    results = in_parallel([assign_call(company, "T-1")] * 10)

    assert all(r == results[0] for r in results)
    assert results[0]["agent_id"] == agent.id
    assert count(session, TicketAssignment) == 1
    assert count(session, AssignmentLog) == 1


def test_two_tickets_one_free_slot(
    session: Session, settings, company, agent, make_ticket
) -> None:
    """#14: the agent is at 1 of 2. Exactly one of two simultaneous tickets
    gets the slot; the agent never exceeds the limit."""
    settings.active_ticket_limit = 2
    make_ticket(agent, "EXISTING", datetime(2026, 10, 12, 9, 0, tzinfo=UTC))

    results = in_parallel([assign_call(company, "T-A"), assign_call(company, "T-B")])

    assert sorted(r["reason_code"] for r in results) == ["FEWEST_ACTIVE", "NO_AGENT_CAPACITY"]
    active = session.scalar(
        select(func.count())
        .select_from(TicketAssignment)
        .where(TicketAssignment.agent_id == agent.id, TicketAssignment.completed_at.is_(None))
    )
    assert active == 2

    loser = next(r["ticket_id"] for r in results if r["agent_id"] is None)
    snapshot = session.scalars(
        select(AssignmentLog.snapshot).where(AssignmentLog.ticket_id == loser)
    ).one()
    assert snapshot["scheduled_agents"][0]["active"] == 2


def test_lock_timeout_returns_503_and_other_companies_proceed(
    client: TestClient, session: Session, settings, company, agent, make_company, make_agent,
    make_shift,
) -> None:
    """While company A's lock is held, /assign for A gives up with 503 and
    writes nothing; company B is unaffected."""
    settings.assignment_lock_timeout_seconds = 0.2
    other = make_company("Other", "UTC")
    make_shift(make_agent(other, timezone="UTC"), "MON", "09:00", "17:00")

    with engine.connect() as holder, holder.begin():
        holder.execute(text("SELECT id FROM company WHERE id = :id FOR UPDATE"), {"id": company.id})

        blocked = client.post(f"/companies/{company.id}/tickets/T-1/assign")
        unblocked = client.post(f"/companies/{other.id}/tickets/T-1/assign")

    assert blocked.status_code == 503
    assert blocked.json()["error"]["code"] == "ASSIGNMENT_LOCK_TIMEOUT"
    assert unblocked.status_code == 200
    assert unblocked.json()["reason_code"] == "FEWEST_ACTIVE"
    rows = session.scalars(select(TicketAssignment.company_id)).all()
    assert rows == [other.id]
