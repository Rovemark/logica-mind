"""Storage backends. SQLiteStore and InMemoryStore need no external services."""
from .base import Store
from .sqlite import SQLiteStore
from .memory import InMemoryStore
from .obsidian import ObsidianStore
from .multi import MultiStore

__all__ = [
    "Store", "SQLiteStore", "InMemoryStore", "ObsidianStore",
    "MultiStore", "SupabaseStore", "PostgresStore", "RedisStore",
]

_LAZY = {
    "SupabaseStore": ".supabase",
    "PostgresStore": ".postgres",
    "RedisStore": ".redis",
}


def __getattr__(name):
    if name in _LAZY:
        import importlib
        return getattr(importlib.import_module(_LAZY[name], __name__), name)
    raise AttributeError(name)
