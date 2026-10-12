from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from clearfeed.api.deps import get_now
from clearfeed.app import app
from clearfeed.models import Company


@pytest.fixture
def set_now() -> Iterator[Callable[[datetime], None]]:
    """Pin the API's clock to a fixed instant."""

    def pin(instant: datetime) -> None:
        app.dependency_overrides[get_now] = lambda: instant

    yield pin
    app.dependency_overrides.pop(get_now, None)


def url(company: Company) -> str:
    return f"/companies/{company.id}/coverage"


def put_required(client: TestClient, company: Company, *windows: tuple[str, str, str]) -> None:
    body = {"windows": [{"day": d, "start": s, "end": e} for d, s, e in windows]}
    assert client.put(f"/companies/{company.id}/required-hours", json=body).status_code == 200


def test_gaps_in_company_time(client: TestClient, make_company, make_agent, make_shift) -> None:
    company = make_company(timezone="Europe/London")
    put_required(client, company, ("MON", "08:00", "20:00"), ("TUE", "08:00", "20:00"))
    make_shift(make_agent(company, timezone="Asia/Kolkata"), "MON", "09:00", "17:00")

    response = client.get(url(company), params={"week_of": "2026-10-14"})

    # Kolkata 09:00-17:00 is London 04:30-12:30 in October (BST).
    assert response.status_code == 200
    assert response.json() == {
        "company_timezone": "Europe/London",
        "week_start": "2026-10-12",
        "fully_covered": False,
        "gaps": [
            {"day": "MON", "date": "2026-10-12", "start": "12:30", "end": "20:00"},
            {"day": "TUE", "date": "2026-10-13", "start": "08:00", "end": "20:00"},
        ],
    }


def test_fully_covered(client: TestClient, make_company, make_agent, make_shift) -> None:
    company = make_company(timezone="UTC")
    put_required(client, company, ("MON", "16:00", "24:00"))
    make_shift(make_agent(company, timezone="UTC"), "MON", "16:00", "24:00")

    body = client.get(url(company), params={"week_of": "2026-10-12"}).json()

    assert body["fully_covered"] is True
    assert body["gaps"] == []


def test_no_required_hours_is_fully_covered(client: TestClient, make_company) -> None:
    body = client.get(url(make_company()), params={"week_of": "2026-10-12"}).json()

    assert (body["fully_covered"], body["gaps"]) == (True, [])


def test_other_companies_agents_dont_count(
    client: TestClient, make_company, make_agent, make_shift
) -> None:
    company = make_company(timezone="UTC")
    put_required(client, company, ("MON", "09:00", "17:00"))
    make_shift(make_agent(make_company("Other"), timezone="UTC"), "MON", "09:00", "17:00")

    gaps = client.get(url(company), params={"week_of": "2026-10-12"}).json()["gaps"]

    assert gaps == [{"day": "MON", "date": "2026-10-12", "start": "09:00", "end": "17:00"}]


def test_default_week_is_current_week_in_company_timezone(
    client: TestClient, make_company, set_now
) -> None:
    # Sunday 23:30 UTC is already Monday 08:30 in Tokyo.
    set_now(datetime(2026, 10, 18, 23, 30, tzinfo=UTC))

    body = client.get(url(make_company(timezone="Asia/Tokyo"))).json()

    assert body["week_start"] == "2026-10-19"


def test_invalid_week_of(client: TestClient, make_company) -> None:
    response = client.get(url(make_company()), params={"week_of": "next-week"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unknown_company(client: TestClient) -> None:
    response = client.get("/companies/999/coverage")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "COMPANY_NOT_FOUND"
