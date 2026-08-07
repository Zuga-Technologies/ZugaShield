"""Collector registry. Each module exposes COLLECTOR, PROVENANCE, INTERVAL, and
async collect() -> CollectResult.

A module that fails to import (missing optional dep, not yet written) is skipped
with a log line — one broken collector must never take down the rest, same rule
as ZugaTreasury's puller registry.
"""

import importlib
import logging

logger = logging.getLogger(__name__)

_MODULES = (
    "agentpool_rail",
    "catalog",
    "version",
    "benchmark",
    "github_issues",
    "redteam_ledger",
)

# id -> module. Ordered so the metrics API can iterate deterministically.
REGISTRY = {}
for _name in _MODULES:
    try:
        _mod = importlib.import_module(f"collectors.{_name}")
        REGISTRY[_mod.COLLECTOR] = _mod
    except ImportError as e:
        logger.warning("collector %s not available: %s", _name, e)
