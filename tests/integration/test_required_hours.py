import pytest
from fastapi.testclient import TestClient

from clearfeed.models import Company


def url(company: Company) -> str:
    return f"/companies/{company.id}/required-hours"


def window(day: str, start: str, end: str) -> dict[str, str]:
    return {"day": day, "start": start, "end": end}


def test_empty_by_default(client: TestClient, make_company) -> None:
    response = client.get(url(make_company()))

    assert response.status_code == 200
    assert response.json() == {"windows": []}


def test_put_then_get_sorted(client: TestClient, make_company) -> None:
    company = make_company()
    windows = [
        window("SAT", "10:00", "14:00"),
        window("MON", "13:00", "20:00"),
        window("MON", "08:00", "12:00"),
    ]
    expected = {"windows": [windows[2], windows[1], windows[0]]}

    put = client.put(url(company), json={"windows": windows})

    assert put.status_code == 200
    assert put.json() == expected
    assert client.get(url(company)).json() == expected


def test_put_replaces_full_set(client: TestClient, make_company) -> None:
    company = make_company()
    client.put(url(company), json={"windows": [window("MON", "08:00", "20:00")]})

    client.put(url(company), json={"windows": [window("TUE", "09:00", "17:00")]})

    assert client.get(url(company)).json() == {"windows": [window("TUE", "09:00", "17:00")]}


def test_empty_list_clears(client: TestClient, make_company) -> None:
    company = make_company()
    client.put(url(company), json={"windows": [window("MON", "08:00", "20:00")]})

    client.put(url(company), json={"windows": []})

    assert client.get(url(company)).json() == {"windows": []}


def test_back_to_back_allowed(client: TestClient, make_company) -> None:
    windows = [window("MON", "08:00", "12:00"), window("MON", "12:00", "20:00")]

    assert client.put(url(make_company()), json={"windows": windows}).status_code == 200


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("16:00", "24:00"),
        ("00:00", "24:00"),  # whole day
        ("16:00", "00:00"),  # 00:00 as an end means 24:00
    ],
)
def test_window_ending_at_midnight(client: TestClient, make_company, start, end) -> None:
    response = client.put(url(make_company()), json={"windows": [window("MON", start, end)]})

    assert response.status_code == 200
    assert response.json() == {"windows": [window("MON", start, "24:00")]}


@pytest.mark.parametrize(
    "windows",
    [
        [window("MON", "08:00", "20:00"), window("MON", "08:00", "20:00")],  # exact duplicate
        [window("MON", "16:00", "24:00"), window("MON", "23:00", "24:00")],
    ],
)
def test_overlapping_windows_rejected(client: TestClient, make_company, windows) -> None:
    response = client.put(url(make_company()), json={"windows": windows})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REQUIRED_HOURS_OVERLAP"


def test_overnight_window_rejected(client: TestClient, make_company) -> None:
    response = client.put(
        url(make_company()), json={"windows": [window("MON", "22:00", "06:00")]}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_overlap_rejected_and_old_set_kept(client: TestClient, make_company) -> None:
    company = make_company()
    original = {"windows": [window("MON", "08:00", "20:00")]}
    client.put(url(company), json=original)

    response = client.put(
        url(company),
        json={"windows": [window("TUE", "08:00", "12:00"), window("TUE", "11:00", "14:00")]},
    )

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "REQUIRED_HOURS_OVERLAP",
        "message": "TUE 08:00-12:00 overlaps TUE 11:00-14:00",
    }
    assert client.get(url(company)).json() == original


def test_companies_are_independent(client: TestClient, make_company) -> None:
    a, b = make_company("A"), make_company("B")
    client.put(url(a), json={"windows": [window("MON", "08:00", "20:00")]})

    client.put(url(b), json={"windows": []})

    assert client.get(url(a)).json() == {"windows": [window("MON", "08:00", "20:00")]}


def test_unknown_company(client: TestClient) -> None:
    response = client.get("/companies/999/required-hours")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "COMPANY_NOT_FOUND"
