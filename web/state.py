"""Shared stats-store access for the web dashboard."""
from __future__ import annotations

import os

from sofascore_client import StatsStore

_stats_store: StatsStore | None = None


def get_admin_token() -> str:
    return os.environ.get("SIM_ADMIN_TOKEN", "changeme")


def get_stats_store() -> StatsStore:
    global _stats_store
    if _stats_store is None:
        _stats_store = StatsStore()
    return _stats_store


def reload_stats_store() -> StatsStore:
    """Reload player cache from disk (e.g. after seed merge)."""
    global _stats_store
    _stats_store = StatsStore()
    return _stats_store
