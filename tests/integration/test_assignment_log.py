from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from clearfeed.models import Agent, Company


@pytest.fixture(autouse=True)
def pinned_clock(set_now) -> None:
    set_now(datetime(2026, 10, 12, 10, 0, tzinfo=UTC))  # Monday


@pytest.fixture
def company(make_company) -> Company:
    return make_company(timezone="UTC")


@pytest.fixture
def agent(company, make_agent, make_shift, settings) -> Agent:
    """One agent on shift who can take two tickets."""
    settings.active_ticket_limit = 2
    agent = make_agent(company, "Priya", "UTC")
    make_shift(agent, "MON", "09:00", "17:00")
    return agent


def log(client: TestClient, company: Company, **params) -> dict:
    response = client.get(f"/companies/{company.id}/assignment-log", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def assign(client: TestClient, company: Company, *ticket_ids: str) -> None:
    for ticket_id in ticket_ids:
        client.post(f"/companies/{company.id}/tickets/{ticket_id}/assign")


def test_items_newest_first_with_outcome_and_agent(client: TestClient, company, agent) -> None:
    assign(client, company, "T-1", "T-2", "T-3")  # third hits the limit

    items = log(client, company)["items"]

    assert [(i["ticket_id"], i["outcome"], i["reason_code"]) for i in items] == [
        ("T-3", "UNASSIGNED", "NO_AGENT_CAPACITY"),
        ("T-2", "ASSIGNED", "FEWEST_ACTIVE"),
        ("T-1", "ASSIGNED", "FEWEST_ACTIVE"),
    ]
    assert items[0]["agent"] is None
    assert items[1]["agent"] == {"id": agent.id, "name": "Priya"}
    assert items[1]["evaluated_at"] == "2026-10-12T10:00:00Z"
    assert items[1]["snapshot"]["scheduled_agents"][0]["agent_id"] == agent.id


def test_filters(client: TestClient, company, agent) -> None:
    assign(client, company, "T-1", "T-2", "T-3")

    unassigned = log(client, company, outcome="UNASSIGNED")["items"]
    by_ticket = log(client, company, ticket_id="T-2")["items"]

    assert [i["ticket_id"] for i in unassigned] == ["T-3"]
    assert [i["ticket_id"] for i in by_ticket] == ["T-2"]


def test_cursor_pagination(client: TestClient, company, agent) -> None:
    assign(client, company, "T-1", "T-2", "T-3")

    first = log(client, company, limit=2)
    second = log(client, company, limit=2, cursor=first["next_cursor"])

    assert [i["ticket_id"] for i in first["items"]] == ["T-3", "T-2"]
    assert [i["ticket_id"] for i in second["items"]] == ["T-1"]
    assert second["next_cursor"] is None


def test_only_this_companys_entries(client: TestClient, company, agent, make_company) -> None:
    other = make_company("Other", "UTC")
    assign(client, company, "T-1")
    assign(client, other, "T-9")

    assert [i["ticket_id"] for i in log(client, company)["items"]] == ["T-1"]
