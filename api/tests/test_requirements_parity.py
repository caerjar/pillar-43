"""The two requirements files must agree on every package they share.

`requirements-desktop.txt` is a near-copy of `requirements.txt` with the
heavyweight extras removed, and nothing kept them in step. They drifted on
exactly one package, and it was the one that mattered: `requirements.txt`
carried a six-line comment pinning `openai>=1.55.3` (since removed with the
SDK) because earlier releases
pass a `proxies` kwarg that httpx 0.28 removed — while the desktop file stayed
at 1.54.3.

The effect was invisible in CI and total in the product. Docker was fixed, so
every test passed; the macOS app shipped with **every** openai-compatible
provider dead on arrival, failing at client construction with
`Client.__init__() got an unexpected keyword argument 'proxies'`. Reported from
a real build, connecting to a local qwen.

Same shape as the wizard-vs-Settings Ollama defaults (`qwen2.5` against
`llama3`): two files describing one thing, with nothing asserting they agree.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

API = Path(__file__).resolve().parent.parent
PIN = re.compile(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?==(.+)$")

# Packages deliberately absent from the desktop build, with the reason. A name
# here is a decision; anything else missing is drift.
DESKTOP_OMITS = {
    "faster-whisper": "too heavy to bundle; services/capabilities.py reports the gap",
}


def _pins(name: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in (API / name).read_text().splitlines():
        line = raw.split("#")[0].strip()
        m = PIN.match(line)
        if m:
            out[m.group(1).lower()] = m.group(3).strip()
    return out


@pytest.fixture(scope="module")
def docker() -> dict[str, str]:
    return _pins("requirements.txt")


@pytest.fixture(scope="module")
def desktop() -> dict[str, str]:
    return _pins("requirements-desktop.txt")


def test_shared_packages_pin_the_same_version(docker, desktop):
    """The guard the openai drift needed."""
    drift = {
        name: (docker[name], desktop[name])
        for name in sorted(set(docker) & set(desktop))
        if docker[name] != desktop[name]
    }
    assert not drift, (
        "requirements.txt and requirements-desktop.txt disagree: "
        + ", ".join(f"{n} docker={d} desktop={k}" for n, (d, k) in drift.items())
    )


def test_desktop_omits_only_what_it_means_to(docker, desktop):
    """A package quietly dropped from the desktop build is a capability quietly
    dropped from the macOS app."""
    missing = set(docker) - set(desktop) - set(DESKTOP_OMITS)
    assert not missing, (
        f"absent from the desktop build with no recorded reason: {sorted(missing)}. "
        "Add it, or name it in DESKTOP_OMITS with why."
    )


def test_no_hosted_provider_sdk_is_pinned(docker, desktop):
    """Pillar-43 talks to local Ollama over httpx; a hosted-provider SDK in
    either requirements file would be a way back to a frontier API."""
    for pins in (docker, desktop):
        assert not {"anthropic", "openai"} & set(pins)
