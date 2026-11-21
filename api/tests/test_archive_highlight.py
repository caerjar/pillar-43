"""A cited passage is located on its PDF page (audit 2026-11-19, finding 9),
and the AI-readable counts by kind come from the same consent test as ask."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.archive_fixtures import seed
from tests.archive_fixtures import settings as org_settings

LINES = [
    "7. Reversion",
    "Rights revert to the Author nine months after written notice.",
    "The Publisher keeps the right to sell remaining stock.",
]
PATH = "library/contracts/c.pdf"


def make_pdf(lines: list[str]) -> bytes:
    """One page, one text line per entry, Helvetica 12 pt, hand-built."""
    stream = (
        "BT /F1 12 Tf 72 700 Td 20 TL\n"
        + "\n".join(f"({ln}) Tj T*" for ln in lines)
        + "\nET"
    )
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF"
    ).encode()
    return out


@pytest.fixture
def pdf(tmp_path, monkeypatch):
    org_settings(tmp_path, monkeypatch)
    p = tmp_path / "library" / "contracts" / "c.pdf"
    p.parent.mkdir(parents=True)
    p.write_bytes(make_pdf(LINES))
    return p


@pytest.fixture
def client():
    from main import app

    return TestClient(app, base_url="http://localhost")


def boxes(client, text):
    return client.get(
        "/api/archive/passage-boxes", params={"path": PATH, "page": 1, "text": text}
    )


def test_exact_text_is_boxed_on_its_own_line(pdf, client):
    seed(PATH, "x", "staff")
    r = boxes(client, LINES[1])
    assert r.status_code == 200
    body = r.json()
    assert body["match"] == "exact"
    assert len(body["boxes"]) == 1
    b = body["boxes"][0]
    assert 0.0 < b["x"] < 0.2 and 0.0 < b["y"] < 0.3 and 0.3 < b["w"] < 0.9
    third = boxes(client, LINES[2]).json()["boxes"][0]
    assert third["y"] > b["y"]


def test_text_not_there_word_for_word_gets_the_nearest_lines(pdf, client):
    seed(PATH, "x", "staff")
    r = boxes(
        client,
        "Rights revert to the Author nine months after the written notice is given.",
    ).json()
    assert r["match"] == "nearest" and r["boxes"]


def test_unrelated_text_is_not_boxed(pdf, client):
    seed(PATH, "x", "staff")
    r = boxes(client, "completely different words about ferries").json()
    assert r["match"] == "none" and r["boxes"] == []


def test_a_closed_item_is_not_served(pdf, client):
    seed(PATH, "x", "private")
    assert boxes(client, LINES[1]).status_code == 404


def test_open_to_ai_counts_by_kind(tmp_path, monkeypatch, client):
    org_settings(tmp_path, monkeypatch)
    seed("library/a.pdf", "x", "model", kind="contract")
    seed("library/b.pdf", "x", "model", kind="contract")
    seed("library/c.txt", "x", "model", kind="letter")
    seed("library/d.txt", "x", "staff", kind="letter")
    seed("library/e.txt", "x", "private", kind="letter")
    body = client.get("/api/archive/open-to-ai").json()
    assert body == {
        "total": 3,
        "by_kind": [
            {"kind": "contract", "count": 2},
            {"kind": "letter", "count": 1},
        ],
    }
