"""Assignment and completion (test plan #5-#12)."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from clearfeed.models import Agent, AssignmentLog, Company, TicketAssignment

# Monday 2026-10-12. Agents below work Mon 09:00-17:00 UTC.
NOW = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)


def at(hhmm: str) -> datetime:
    return datetime.fromisoformat(f"2026-10-12T{hhmm}").replace(tzinfo=UTC)


@pytest.fixture(autouse=True)
def pinned_clock(set_now) -> None:
    set_now(NOW)


@pytest.fixture
def company(make_company) -> Company:
    return make_company(timezone="UTC")


@pytest.fixture
def on_shift(make_agent, make_shift) -> Callable[..., Agent]:
    """Create an agent working Mon 09:00-17:00 UTC."""

    def make(company: Company, name: str = "Agent") -> Agent:
        agent = make_agent(company, name, "UTC")
        make_shift(agent, "MON", "09:00", "17:00")
        return agent

    return make


def assign(client: TestClient, company: Company, ticket_id: str) -> dict:
    response = client.post(f"/companies/{company.id}/tickets/{ticket_id}/assign")
    assert response.status_code == 200, response.text
    return response.json()


def complete(client: TestClient, company: Company, ticket_id: str):
    return client.post(f"/companies/{company.id}/tickets/{ticket_id}/complete")


def log_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(AssignmentLog))


def active_count(session: Session, agent: Agent) -> int:
    return session.scalar(
        select(func.count())
        .select_from(TicketAssignment)
        .where(TicketAssignment.agent_id == agent.id, TicketAssignment.completed_at.is_(None))
    )


# --- ranking (#5-#8) ---


def test_assigned_response(client: TestClient, company, on_shift) -> None:
    agent = on_shift(company)

    assert assign(client, company, "T-1") == {
        "company_id": company.id,
        "ticket_id": "T-1",
        "agent_id": agent.id,
        "reason_code": "FEWEST_ACTIVE",
        "assigned_at": "2026-10-12T10:00:00Z",
        "completed_at": None,
    }


def test_fewest_active_wins_and_limit_and_schedule_respected(
    client: TestClient, settings, company, on_shift, make_agent, make_ticket
) -> None:
    """#5: lowest load wins; an agent at the limit or out of shift is never chosen."""
    settings.active_ticket_limit = 2
    busy = on_shift(company, "busy")  # 1 active
    full = on_shift(company, "full")  # at the limit
    free = on_shift(company, "free")  # 0 active, but assigned recently
    make_agent(company, "off-shift", "UTC")  # no shifts, 0 active
    make_ticket(busy, "B-1", at("09:00"))
    make_ticket(full, "F-1", at("09:00"))
    make_ticket(full, "F-2", at("09:00"))
    make_ticket(free, "X-1", at("09:30"), completed_at=at("09:45"))

    result = assign(client, company, "T-1")

    assert (result["agent_id"], result["reason_code"]) == (free.id, "FEWEST_ACTIVE")


def test_tie_uses_most_recent_assignment(
    client: TestClient, company, on_shift, make_ticket
) -> None:
    """#6: A assigned at 09:00 and 09:55, B at 09:30, all completed. B wins
    because A's latest assignment (MAX, not MIN) is more recent."""
    a, b = on_shift(company, "A"), on_shift(company, "B")
    make_ticket(a, "A-1", at("09:00"), completed_at=at("09:10"))
    make_ticket(a, "A-2", at("09:55"), completed_at=at("09:58"))
    make_ticket(b, "B-1", at("09:30"), completed_at=at("09:40"))

    result = assign(client, company, "T-1")

    assert (result["agent_id"], result["reason_code"]) == (b.id, "TIE_LONGEST_SINCE_ASSIGNED")


def test_never_assigned_beats_history(client: TestClient, company, on_shift, make_ticket) -> None:
    """#7"""
    veteran, newcomer = on_shift(company, "veteran"), on_shift(company, "newcomer")
    make_ticket(veteran, "V-1", at("09:00"), completed_at=at("09:10"))

    result = assign(client, company, "T-1")

    assert result["agent_id"] == newcomer.id
    assert result["reason_code"] == "TIE_LONGEST_SINCE_ASSIGNED"


def test_two_never_assigned_go_to_lowest_id(client: TestClient, company, on_shift) -> None:
    """#7"""
    first, _ = on_shift(company, "first"), on_shift(company, "second")

    result = assign(client, company, "T-1")

    assert (result["agent_id"], result["reason_code"]) == (first.id, "TIE_AGENT_ID")


def test_no_agent_scheduled(client: TestClient, company, make_agent, make_shift) -> None:
    """#8"""
    make_shift(make_agent(company), "TUE", "09:00", "17:00")

    result = assign(client, company, "T-1")

    assert (result["agent_id"], result["reason_code"]) == (None, "NO_AGENT_SCHEDULED")
    assert result["assigned_at"] is None


def test_no_agent_capacity(
    client: TestClient, settings, company, on_shift, make_ticket
) -> None:
    """#8"""
    settings.active_ticket_limit = 1
    make_ticket(on_shift(company), "A-1", at("09:00"))

    result = assign(client, company, "T-1")

    assert (result["agent_id"], result["reason_code"]) == (None, "NO_AGENT_CAPACITY")


def test_shift_boundaries(client: TestClient, set_now, company, on_shift) -> None:
    """Start inclusive, end exclusive, at the assignment level."""
    on_shift(company)

    set_now(at("09:00:00"))
    assert assign(client, company, "T-start")["reason_code"] == "FEWEST_ACTIVE"
    set_now(at("17:00:00"))
    assert assign(client, company, "T-end")["reason_code"] == "NO_AGENT_SCHEDULED"


def test_snapshot_in_log(
    client: TestClient, session: Session, company, make_agent, make_shift, make_ticket
) -> None:
    agent = make_agent(company, "Priya", "Asia/Kolkata")
    make_shift(agent, "MON", "09:00", "17:00")  # 03:30-11:30 UTC
    make_ticket(agent, "P-1", at("08:50"))

    assign(client, company, "T-1")

    entry = session.scalars(select(AssignmentLog)).one()
    assert entry.snapshot == {
        "active_ticket_limit": 5,
        "scheduled_agents": [
            {
                "agent_id": agent.id,
                "active": 1,
                "last_assigned_at": "2026-10-12T08:50:00Z",
                "local_tz": "Asia/Kolkata",
                "matched_shift": {"day": "MON", "start": "09:00", "end": "17:00"},
            }
        ],
    }


# --- retries and completion (#9-#11) ---


def test_assigned_retry_returns_stored_result(
    client: TestClient, session: Session, set_now, company, on_shift
) -> None:
    """#9: same body, no new log entry, no count change, even after the shift ended."""
    agent = on_shift(company)
    first = assign(client, company, "T-1")

    set_now(at("18:00"))  # shift is over
    second = assign(client, company, "T-1")

    assert second == first
    assert log_count(session) == 1
    assert active_count(session, agent) == 1


def test_completed_retry_includes_completion(
    client: TestClient, session: Session, set_now, company, on_shift
) -> None:
    """#9"""
    on_shift(company)
    assign(client, company, "T-1")
    set_now(at("10:30"))
    complete(client, company, "T-1")

    result = assign(client, company, "T-1")

    assert result["completed_at"] == "2026-10-12T10:30:00Z"
    assert log_count(session) == 1


def test_unassigned_retry_is_reevaluated(
    client: TestClient, session: Session, settings, company, on_shift, make_ticket
) -> None:
    """#10: NO_AGENT_CAPACITY, then capacity frees up, and the retry assigns
    the same row and writes a second log entry."""
    settings.active_ticket_limit = 1
    agent = on_shift(company)
    make_ticket(agent, "A-1", at("09:00"))
    assert assign(client, company, "T-1")["reason_code"] == "NO_AGENT_CAPACITY"

    complete(client, company, "A-1")
    result = assign(client, company, "T-1")

    assert (result["agent_id"], result["reason_code"]) == (agent.id, "FEWEST_ACTIVE")
    assert session.scalar(select(func.count()).select_from(TicketAssignment)) == 2  # A-1, T-1
    assert log_count(session) == 2


def test_completion_frees_capacity_once(
    client: TestClient, session: Session, set_now, company, on_shift
) -> None:
    """#11: first call sets completed_at and frees one slot; a repeat returns
    the same completed_at without freeing another."""
    agent = on_shift(company)
    assign(client, company, "T-1")
    assign(client, company, "T-2")
    set_now(at("10:30"))

    first = complete(client, company, "T-1")
    set_now(at("10:45"))
    repeat = complete(client, company, "T-1")

    assert first.status_code == repeat.status_code == 200
    assert first.json() == repeat.json() == {
        "ticket_id": "T-1",
        "agent_id": agent.id,
        "completed_at": "2026-10-12T10:30:00Z",
    }
    assert active_count(session, agent) == 1


def test_complete_unknown_ticket(client: TestClient, session: Session, company) -> None:
    """#11: 404 and no row created."""
    response = complete(client, company, "nope")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TICKET_NOT_FOUND"
    assert session.scalar(select(func.count()).select_from(TicketAssignment)) == 0


def test_complete_unassigned_ticket(client: TestClient, company, on_shift, make_agent) -> None:
    """#11: 409, and the ticket can still be assigned later."""
    assign(client, company, "T-1")  # nobody scheduled yet

    response = complete(client, company, "T-1")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TICKET_NOT_ASSIGNED"

    agent = on_shift(company)
    assert assign(client, company, "T-1")["agent_id"] == agent.id


# --- isolation (#12) ---


def test_never_assigns_another_companys_agent(
    client: TestClient, company, make_company, on_shift
) -> None:
    on_shift(make_company("Other", "UTC"))

    assert assign(client, company, "T-1")["reason_code"] == "NO_AGENT_SCHEDULED"


def test_same_ticket_id_in_two_companies_is_independent(
    client: TestClient, session: Session, company, make_company, on_shift
) -> None:
    other = make_company("Other", "UTC")
    agent_a, agent_b = on_shift(company, "A"), on_shift(other, "B")

    assert assign(client, company, "T-1")["agent_id"] == agent_a.id
    assert assign(client, other, "T-1")["agent_id"] == agent_b.id

    complete(client, company, "T-1")

    assert active_count(session, agent_a) == 0
    assert active_count(session, agent_b) == 1


def test_unknown_company(client: TestClient) -> None:
    response = client.post("/companies/999/tickets/T-1/assign")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "COMPANY_NOT_FOUND"
