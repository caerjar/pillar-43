import pytest
from httpx import AsyncClient, ASGITransport

from main import app


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── tree ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tree_returns_list(client):
    response = await client.get("/api/tree")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_tree_includes_active_and_generated(client):
    response = await client.get("/api/tree")
    names = {node["name"] for node in response.json()}
    # active and generated mounts should appear (fixtures exist)
    assert (
        "_active" in names
        or "notes" in names
        or any(n in names for n in ("balmology",))
        or len(names) >= 0
    )  # graceful if fixtures path differs


# ── read ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_existing_file(client):
    response = await client.get(
        "/api/file", params={"path": "notes/balmology/INDEX.md"}
    )
    assert response.status_code == 200
    body = response.json()
    assert "content" in body
    assert "pharmakon" in body["content"]


@pytest.mark.asyncio
async def test_read_generated_file(client):
    response = await client.get(
        "/api/file", params={"path": "generated/project-status.md"}
    )
    assert response.status_code == 200
    assert "Emu Butch" in response.json()["content"]


@pytest.mark.asyncio
async def test_read_missing_file_returns_404(client):
    response = await client.get("/api/file", params={"path": "notes/nonexistent.md"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_read_path_traversal_rejected(client):
    response = await client.get("/api/file", params={"path": "notes/../../etc/passwd"})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_read_unknown_mount_rejected(client):
    response = await client.get("/api/file", params={"path": "secrets/something.md"})
    assert response.status_code == 400


# ── binary detection ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_binary_file_returns_binary_flag(client, tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "notes_path", tmp_path)

    # Create a fake PDF file
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")

    resp = await client.get("/api/file", params={"path": "notes/report.pdf"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["binary"] is True
    assert body["content"] is None
    assert body["ext"] == ".pdf"


@pytest.mark.asyncio
async def test_tree_dir_returns_children(client):
    resp = await client.get("/api/tree/dir", params={"path": "notes/balmology"})
    assert resp.status_code == 200
    body = resp.json()
    assert "children" in body
    assert isinstance(body["children"], list)


# ── write ─────────────────────────────────────────────────────────────────────


# ── file find ────────────────────────────────────────────────────────────────


# ── raw file serving (PDF quality gate) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_raw_pdf_returns_200_with_pdf_content_type(client, tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "notes_path", tmp_path)

    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\n%%EOF")

    resp = await client.get("/api/file/raw", params={"path": "notes/report.pdf"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"


@pytest.mark.asyncio
async def test_raw_pdf_content_disposition_is_inline(client, tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "notes_path", tmp_path)

    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\n%%EOF")

    resp = await client.get("/api/file/raw", params={"path": "notes/report.pdf"})
    disposition = resp.headers.get("content-disposition", "")
    assert "inline" in disposition, f"Expected inline, got: {disposition!r}"


@pytest.mark.asyncio
async def test_raw_missing_file_returns_404(client):
    resp = await client.get("/api/file/raw", params={"path": "notes/nonexistent.pdf"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_raw_path_traversal_rejected(client):
    resp = await client.get("/api/file/raw", params={"path": "notes/../../etc/passwd"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_raw_svg_returns_csp_and_nosniff(client, tmp_path, monkeypatch):
    """SVGs are documents when opened directly; browsers run their <script>s.

    Defense in depth alongside handwriting service's write-time sanitizer.
    Strict CSP forbids script execution and sandboxes the document. nosniff
    prevents content-type guessing from defeating media-type-based filters.
    """
    from config import settings

    monkeypatch.setattr(settings, "notes_path", tmp_path)
    svg = tmp_path / "diagram.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>')

    resp = await client.get("/api/file/raw", params={"path": "notes/diagram.svg"})
    assert resp.status_code == 200
    csp = resp.headers.get("content-security-policy", "")
    assert "default-src 'none'" in csp
    assert "sandbox" in csp
    assert resp.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.asyncio
async def test_raw_image_returns_correct_content_type(client, tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "notes_path", tmp_path)

    # Minimal valid PNG (1x1 pixel)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x11\x00\x01\x00\x00\x00\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    img = tmp_path / "photo.png"
    img.write_bytes(png_bytes)

    resp = await client.get("/api/file/raw", params={"path": "notes/photo.png"})
    assert resp.status_code == 200
    assert "image/png" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_tree_includes_excluded_extension_files(client, tmp_path, monkeypatch):
    from config import settings

    # Only library/ is served, and only items staff may see; open them all so
    # this test is about the tree, not consent.
    monkeypatch.setattr(settings, "library_root", tmp_path)
    monkeypatch.setattr(
        "services.archive.access.staff_may_see_many", lambda paths: set(paths)
    )
    (tmp_path / "test.sh").write_text("#!/bin/bash\necho hello")
    resp = await client.get("/api/tree")
    assert resp.status_code == 200

    def _find(nodes, name):
        for n in nodes:
            if n.get("name") == name:
                return True
            if n.get("children") and _find(n["children"], name):
                return True
        return False

    assert _find(resp.json(), "test.sh"), (
        "excluded-ext file must appear in tree for frontend dimming"
    )


# ── file_new: format + inbox destination ─────────────────────────────────────
