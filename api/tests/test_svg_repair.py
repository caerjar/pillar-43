"""SVG handling: malformed model-generated SVG is repaired before it reaches
disk, and .svg is treated as editable text (not a binary blob) so the editor
opens it as source. See plans/shimmying-kindling-firefly.md Fix 3."""

from lxml import etree

from services.vault.constants import BINARY_EXTENSIONS
from services.vault.io import _repair_svg_if_malformed

_VALID = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'


def _is_well_formed(svg: str) -> bool:
    try:
        etree.fromstring(svg.encode("utf-8"))
        return True
    except etree.XMLSyntaxError:
        return False


def test_valid_svg_passes_through_untouched():
    # Already well-formed SVG must not be reformatted (byte-for-byte identity).
    assert _repair_svg_if_malformed(_VALID) == _VALID


def test_malformed_svg_is_repaired_to_well_formed():
    # Broken attribute value (the `AttValue: ' expected`-class corruption the
    # browser refused to render).
    bad = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<text font-family="Times"New Roman">hi</text></svg>'
    )
    assert not _is_well_formed(bad)
    out = _repair_svg_if_malformed(bad)
    assert _is_well_formed(out)


def test_unescaped_ampersand_is_repaired():
    bad = '<svg xmlns="http://www.w3.org/2000/svg"><title>R&D</title></svg>'
    out = _repair_svg_if_malformed(bad)
    assert _is_well_formed(out)


def test_unrecoverable_input_returned_as_is_for_manual_fix():
    # Garbage that can't be parsed into a root element is returned verbatim so
    # the editor can still surface it.
    junk = "not svg at all <<<"
    assert _repair_svg_if_malformed(junk) == junk


def test_svg_is_not_a_binary_extension():
    # .svg must be editable text so the editor routes it to CodeMirror, not the
    # read-only image viewer.
    assert ".svg" not in BINARY_EXTENSIONS
