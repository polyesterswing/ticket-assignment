from fastapi.testclient import TestClient

from clearfeed.app import app

client = TestClient(app)


def test_unknown_route_uses_error_format() -> None:
    response = client.get("/companies/1/nope")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "NOT_FOUND", "message": "Not Found"}}


def test_wrong_method_uses_error_format() -> None:
    response = client.delete("/companies/1/coverage")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert response.headers["allow"] == "GET"
