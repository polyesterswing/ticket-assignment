from threading import Barrier
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from clearfeed.app import app
from clearfeed.models import Agent, Shift


def shifts_url(agent: Agent) -> str:
    return f"/companies/{agent.company_id}/agents/{agent.id}/shifts"


def body(day: str, start: str, end: str) -> dict[str, str]:
    return {"day": day, "start": start, "end": end}


@pytest.fixture
def agent(make_company, make_agent) -> Agent:
    return make_agent(make_company())


def test_create_and_list_sorted_by_day_then_start(client: TestClient, agent: Agent) -> None:
    created = client.post(shifts_url(agent), json=body("WED", "09:00", "17:00"))
    client.post(shifts_url(agent), json=body("MON", "22:00", "06:00"))
    client.post(shifts_url(agent), json=body("MON", "08:00", "12:00"))

    assert created.status_code == 201
    assert created.json() == {"id": 1, "day": "WED", "start": "09:00", "end": "17:00"}

    listed = client.get(shifts_url(agent)).json()
    assert [(s["day"], s["start"]) for s in listed] == [
        ("MON", "08:00"),
        ("MON", "22:00"),
        ("WED", "09:00"),
    ]


def test_end_of_00_00_returned_as_24_00(client: TestClient, agent: Agent) -> None:
    response = client.post(shifts_url(agent), json=body("MON", "22:00", "00:00"))

    assert response.status_code == 201
    assert (response.json()["start"], response.json()["end"]) == ("22:00", "24:00")


def test_start_of_24_00_rejected(client: TestClient, agent: Agent) -> None:
    response = client.post(shifts_url(agent), json=body("MON", "24:00", "06:00"))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_overlap_across_days_rejected(client: TestClient, agent: Agent, make_shift) -> None:
    make_shift(agent, "MON", "22:00", "06:00")

    response = client.post(shifts_url(agent), json=body("TUE", "05:00", "08:00"))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SHIFT_OVERLAP"
    assert len(client.get(shifts_url(agent)).json()) == 1


@pytest.mark.parametrize(
    ("existing", "new"),
    [
        (("MON", "08:00", "12:00"), ("MON", "12:00", "20:00")),
        (("MON", "22:00", "06:00"), ("TUE", "06:00", "08:00")),
    ],
)
def test_back_to_back_allowed(client: TestClient, agent: Agent, make_shift, existing, new) -> None:
    make_shift(agent, *existing)

    assert client.post(shifts_url(agent), json=body(*new)).status_code == 201


def test_replace_does_not_conflict_with_itself(
    client: TestClient, agent: Agent, make_shift
) -> None:
    shift = make_shift(agent, "MON", "09:00", "17:00")

    response = client.put(f"{shifts_url(agent)}/{shift.id}", json=body("MON", "10:00", "18:00"))

    assert response.status_code == 200
    assert response.json() == {"id": shift.id, "day": "MON", "start": "10:00", "end": "18:00"}


def test_replace_with_overlap_rejected_and_unchanged(
    client: TestClient, agent: Agent, make_shift
) -> None:
    make_shift(agent, "MON", "09:00", "12:00")
    shift = make_shift(agent, "MON", "13:00", "17:00")

    response = client.put(f"{shifts_url(agent)}/{shift.id}", json=body("MON", "11:00", "15:00"))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SHIFT_OVERLAP"
    stored = next(s for s in client.get(shifts_url(agent)).json() if s["id"] == shift.id)
    assert (stored["start"], stored["end"]) == ("13:00", "17:00")


def test_delete(client: TestClient, agent: Agent, make_shift) -> None:
    shift = make_shift(agent, "MON", "09:00", "17:00")

    assert client.delete(f"{shifts_url(agent)}/{shift.id}").status_code == 204
    second = client.delete(f"{shifts_url(agent)}/{shift.id}")
    assert second.status_code == 404
    assert second.json()["error"]["code"] == "SHIFT_NOT_FOUND"


def test_validation_error_format(client: TestClient, agent: Agent) -> None:
    response = client.post(shifts_url(agent), json=body("FUN", "09:00", "17:00"))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# --- isolation ---


def test_unknown_company(client: TestClient, agent: Agent) -> None:
    response = client.get(f"/companies/999/agents/{agent.id}/shifts")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "COMPANY_NOT_FOUND"


def test_agent_from_another_company_not_found(
    client: TestClient, session: Session, make_company, make_agent
) -> None:
    company_a = make_company("A")
    other_agent = make_agent(make_company("B"))
    url = f"/companies/{company_a.id}/agents/{other_agent.id}/shifts"

    for response in (client.get(url), client.post(url, json=body("MON", "09:00", "17:00"))):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "AGENT_NOT_FOUND"

    assert session.scalar(select(func.count()).select_from(Shift)) == 0


def test_shift_from_another_agent_not_found(
    client: TestClient, session: Session, make_company, make_agent, make_shift
) -> None:
    company = make_company()
    agent = make_agent(company, "A")
    owner = make_agent(company, "B")
    shift = make_shift(owner, "MON", "09:00", "17:00")
    url = f"{shifts_url(agent)}/{shift.id}"

    for response in (client.put(url, json=body("TUE", "10:00", "11:00")), client.delete(url)):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SHIFT_NOT_FOUND"

    session.refresh(shift)
    assert (shift.day_of_week, shift.start_minute, shift.end_minute) == (0, 540, 1020)


# --- concurrency ---


def test_concurrent_overlapping_creates_save_only_one(
    session: Session, agent: Agent
) -> None:
    """Without the agent row lock, several requests could pass the overlap check
    before any of them commits. Starts differ so the unique constraint on
    (agent, day, start) can't be what stops them."""
    n = 10
    barrier = Barrier(n)

    def create(i: int) -> int:
        with TestClient(app) as client:
            barrier.wait()
            return client.post(shifts_url(agent), json=body("MON", f"09:{i:02d}", "17:00")).status_code

    with ThreadPoolExecutor(max_workers=n) as pool:
        statuses = list(pool.map(create, range(n)))

    assert sorted(statuses) == [201] + [422] * (n - 1)
    assert session.scalar(select(func.count()).select_from(Shift)) == 1
