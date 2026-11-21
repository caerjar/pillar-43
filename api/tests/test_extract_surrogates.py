"""Tests for the UTF-8 surrogate stripping in catalog text extraction.

Regression: a malformed PDF in the user's library leaked an unpaired
U+DC53 surrogate code point through pypdf. SQLite refuses to write strings
containing surrogates ("surrogates not allowed"), so that file's catalog
row was never persisted. The log filled with:

    'utf-8' codec can't encode character '\\udc53' in position 75922:
    surrogates not allowed

The fix is at the extraction boundary: _strip_surrogates replaces every
unpaired surrogate with U+FFFD before returning text to upstream code.
See MAINTAIN_PANEL_PLAN.md §0 'UTF-8 surrogate encoding error'.
"""

from services.catalog.extract import _strip_surrogates


def test_strip_surrogates_replaces_unpaired_surrogate():
    """A single surrogate code point becomes U+FFFD."""
    dirty = "abc\udc53def"
    clean = _strip_surrogates(dirty)
    assert clean is not None
    assert "\udc53" not in clean
    assert "�" in clean
    # Encodes cleanly to UTF-8 — this is the property that matters for SQLite.
    clean.encode("utf-8")


def test_strip_surrogates_passes_clean_text_through():
    """Strings with no surrogates are returned unchanged."""
    clean_text = "Hello, world. 中文 emoji 😀 ok"
    result = _strip_surrogates(clean_text)
    assert result == clean_text
    result.encode("utf-8")


def test_strip_surrogates_handles_none_and_empty():
    """None and empty strings are passed through as-is (no exception)."""
    assert _strip_surrogates(None) is None
    assert _strip_surrogates("") == ""


def test_strip_surrogates_replaces_full_range():
    """Every code point in U+D800–U+DFFF is replaced. Spot check a sample
    that previously crashed catalog writes."""
    chars = [chr(0xD800), chr(0xD9AB), chr(0xDC53), chr(0xDFFF)]
    dirty = "before" + "".join(chars) + "after"
    clean = _strip_surrogates(dirty)
    for c in chars:
        assert c not in clean
    assert clean.startswith("before")
    assert clean.endswith("after")
    clean.encode("utf-8")
