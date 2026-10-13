from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from clearfeed.models import Agent


def agent_url(agent: Agent) -> str:
    return f"/companies/{agent.company_id}/agents/{agent.id}"


def test_list_companies(client: TestClient, make_company) -> None:
    make_company("Acme", "Europe/London")
    make_company("Globex", "America/New_York")

    assert client.get("/companies").json() == [
        {"id": 1, "name": "Acme", "timezone": "Europe/London"},
        {"id": 2, "name": "Globex", "timezone": "America/New_York"},
    ]


def test_list_agents_only_for_company(client: TestClient, make_company, make_agent) -> None:
    acme, globex = make_company("Acme"), make_company("Globex")
    make_agent(acme, "Priya", "Asia/Kolkata")
    make_agent(globex, "Lena", "America/New_York")

    agents = client.get(f"/companies/{acme.id}/agents").json()

    assert [(a["name"], a["company_id"], a["timezone"]) for a in agents] == [
        ("Priya", acme.id, "Asia/Kolkata")
    ]


def test_update_timezone(client: TestClient, make_company, make_agent) -> None:
    agent = make_agent(make_company(), "Priya", "Asia/Kolkata")
    listed = client.get(f"/companies/{agent.company_id}/agents").json()
    before = datetime.fromisoformat(listed[0]["updated_at"])

    response = client.patch(agent_url(agent), json={"timezone": "Europe/London"})

    assert response.status_code == 200
    body = response.json()
    assert (body["id"], body["name"], body["timezone"]) == (agent.id, "Priya", "Europe/London")
    assert datetime.fromisoformat(body["updated_at"]) > before


@pytest.mark.parametrize(
    "body",
    [{"timezone": "IST"}, {"timezone": 530}, {}],
    ids=["abbreviation", "not-a-string", "missing"],
)
def test_invalid_timezone_rejected_and_unchanged(
    client: TestClient, session: Session, make_company, make_agent, body
) -> None:
    agent = make_agent(make_company(), timezone="Asia/Kolkata")

    response = client.patch(agent_url(agent), json=body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_TIMEZONE"
    session.refresh(agent)
    assert agent.timezone == "Asia/Kolkata"


def test_agent_from_another_company_not_found(
    client: TestClient, session: Session, make_company, make_agent
) -> None:
    company = make_company("A")
    other = make_agent(make_company("B"), timezone="Asia/Kolkata")

    response = client.patch(
        f"/companies/{company.id}/agents/{other.id}", json={"timezone": "Europe/London"}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AGENT_NOT_FOUND"
    session.refresh(other)
    assert other.timezone == "Asia/Kolkata"


def test_timezone_change_keeps_shift_local_times_and_updates_coverage(
    client: TestClient, make_company, make_agent, make_shift
) -> None:
    """Test plan #15: same shift, same local clock times, new timezone."""
    company = make_company(timezone="Europe/London")
    agent = make_agent(company, timezone="Asia/Kolkata")
    shift = make_shift(agent, "MON", "09:00", "17:00")
    client.put(
        f"/companies/{company.id}/required-hours",
        json={"windows": [{"day": "MON", "start": "08:00", "end": "20:00"}]},
    )
    coverage_url = f"/companies/{company.id}/coverage?week_of=2026-10-12"

    def gaps() -> list[tuple[str, str]]:
        return [(g["start"], g["end"]) for g in client.get(coverage_url).json()["gaps"]]

    # Kolkata 09:00-17:00 is London 04:30-12:30 (BST).
    assert gaps() == [("12:30", "20:00")]

    client.patch(agent_url(agent), json={"timezone": "Europe/London"})

    shifts = client.get(f"{agent_url(agent)}/shifts").json()
    assert shifts == [{"id": shift.id, "day": "MON", "start": "09:00", "end": "17:00"}]
    assert gaps() == [("08:00", "09:00"), ("17:00", "20:00")]
