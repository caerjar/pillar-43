import pytest
from httpx import AsyncClient, ASGITransport

from main import app


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_search_returns_results(client, monkeypatch):
    # Consent is tested in test_archive_access; open every path here.
    monkeypatch.setattr(
        "services.archive.access.staff_may_see_many", lambda paths: set(paths)
    )
    response = await client.get(
        "/api/search", params={"q": "pharmakon", "scope": "notes"}
    )
    assert response.status_code == 200
    body = response.json()
    assert "results" in body
    assert len(body["results"]) >= 1
    assert body["results"][0]["text"]


@pytest.mark.asyncio
async def test_search_result_has_path_line_text(client):
    response = await client.get("/api/search", params={"q": "pharmakon"})
    assert response.status_code == 200
    results = response.json()["results"]
    for r in results:
        assert "path" in r
        assert "line" in r
        assert "text" in r


@pytest.mark.asyncio
async def test_search_invalid_scope(client):
    response = await client.get(
        "/api/search", params={"q": "pharmakon", "scope": "nowhere"}
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_search_no_results(client):
    response = await client.get(
        "/api/search",
        params={"q": "zzzzzzZZZZZZunlikelytofindthisstring999", "scope": "notes"},
    )
    assert response.status_code == 200
    assert response.json()["results"] == []
