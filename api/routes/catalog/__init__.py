"""catalog routes package: read-only `/stats`.

The Maintain pipeline routes (run, passes) were removed with the
personal-only prune.
"""

import logging

from fastapi import APIRouter

log = logging.getLogger("routes.catalog")

# Explicitly annotated: `read` does `from . import router`, and that cycle
# stops mypy inferring the type from the assignment alone.
router: APIRouter = APIRouter(prefix="/api/catalog")

from . import read
