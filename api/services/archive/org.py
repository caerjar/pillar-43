"""Organization config for the press archive.

Nothing here is specific to any one organization; everything that is lives in
the YAML file named by `ORG_CONFIG` (default: `api/orgs/press.yaml`, the
first site).

Read at call time, not import time, so a config edit takes effect without a
rebuild.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from fnmatch import fnmatch
from functools import lru_cache
from pathlib import Path

import yaml

CONSENT_LEVELS: tuple[str, ...] = ("private", "staff", "model")
_DEFAULT_ORG = Path(__file__).resolve().parents[2] / "orgs" / "archive.yaml"


def _glob(path: str, pat: str) -> bool:
    """fnmatch, where a leading `**/` also matches zero folders.

    Plain fnmatch reads `**/contracts/**` as needing a character before
    `/contracts/`, so a top-level `contracts/` folder fell through to the
    catch-all kind and got the wrong default consent."""
    pat = pat.lstrip("/")
    if fnmatch(path, pat):
        return True
    while pat.startswith("**/"):
        pat = pat[3:]
        if fnmatch(path, pat):
            return True
    return False


@dataclass(frozen=True)
class KindRule:
    kind: str
    match: tuple[str, ...]
    default: str


PURPOSES: tuple[str, ...] = (
    "ask",
    "teaching-packet",
    "editorial-history",
    "training",
    "export",
)
AIPREF_KEYS: tuple[str, ...] = ("train-ai", "ai-use", "search")


@dataclass(frozen=True)
class LabelRule:
    """A writer's term of use. `only` (a whitelist of purposes) or `deny`
    (a blacklist) decides what the AI may do with the item; `roles`, if set,
    restricts the permitted purposes to callers holding one of those roles.
    `aipref` is the same term in the IETF AI-preferences vocabulary."""

    id: str
    name: str
    aipref: dict = field(default_factory=dict)
    only: tuple[str, ...] | None = None
    deny: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    attribution: bool = False

    def permits(self, purpose: str, role: str | None) -> bool:
        if self.only is not None and purpose not in self.only:
            return False
        if purpose in self.deny:
            return False
        return not (self.roles and role not in self.roles)


@dataclass(frozen=True)
class OrgConfig:
    org_name: str
    title: str
    kinds: tuple[KindRule, ...]
    roles: tuple[str, ...] = ()
    rights_fields: tuple[str, ...] = ()
    models: dict = field(default_factory=dict)
    labels: dict = field(default_factory=dict)
    aipref_draft: str = ""

    def classify(self, rel_path: str) -> KindRule | None:
        """First kind rule whose glob matches. Paths are matched with a
        leading slash so `**/contracts/**` also matches a top-level folder."""
        p = rel_path.lstrip("/")
        for rule in self.kinds:
            if any(_glob(p, pat) for pat in rule.match):
                return rule
        return None

    @property
    def answer_model(self) -> str:
        return str(self.models.get("answer", "qwen3:8b"))


def config_path() -> Path:
    return Path(os.getenv("ORG_CONFIG", "").strip() or _DEFAULT_ORG)


@lru_cache(maxsize=8)
def _load(path: str, mtime: float) -> OrgConfig:  # noqa: ARG001 - mtime is the lru_cache key, so an edited org.yaml is re-read
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    kinds = []
    for k in raw.get("kinds", []):
        default = k.get("default", "private")
        if default not in CONSENT_LEVELS:
            raise ValueError(
                f"org.yaml: kind {k.get('kind')!r} has unknown default {default!r}"
            )
        match = k.get("match", [])
        kinds.append(
            KindRule(
                kind=k["kind"],
                match=tuple([match] if isinstance(match, str) else match),
                default=default,
            )
        )
    labels = {}
    for lid, spec in (raw.get("labels") or {}).items():
        spec = spec or {}
        aipref = dict(spec.get("aipref") or {})
        for k, v in aipref.items():
            if k not in AIPREF_KEYS or v not in ("y", "n"):
                raise ValueError(f"org.yaml: label {lid!r} has bad aipref {k}={v}")
        only = spec.get("only")
        for pur in list(only or []) + list(spec.get("deny") or []):
            if pur not in PURPOSES:
                raise ValueError(
                    f"org.yaml: label {lid!r} names unknown purpose {pur!r}"
                )
        labels[lid] = LabelRule(
            id=lid,
            name=spec.get("name", lid),
            aipref=aipref,
            only=tuple(only) if only is not None else None,
            deny=tuple(spec.get("deny") or ()),
            roles=tuple(spec.get("roles") or ()),
            attribution=bool(spec.get("attribution", False)),
        )
    return OrgConfig(
        org_name=raw.get("org_name", "this organization"),
        title=raw.get("title", "Local Archive"),
        kinds=tuple(kinds),
        roles=tuple(raw.get("roles", [])),
        rights_fields=tuple(raw.get("rights_fields", [])),
        models=dict(raw.get("models", {})),
        labels=labels,
        aipref_draft=str(raw.get("aipref_draft", "")),
    )


def load_org() -> OrgConfig:
    p = config_path()
    return _load(str(p), p.stat().st_mtime)
