"""AI routes package: the local-models discovery endpoint only.

The hosted-chat, inline, classify, folder-generate and agent routers were
removed with the personal-only prune.
"""

import logging

from fastapi import APIRouter

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai")

from . import _provider  # noqa: E402

router.include_router(_provider.router)
