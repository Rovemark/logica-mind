"""Views of the canonical store that keep personal partitions out of shared reads.

No second database: all writes use the original Store. Private partitions never
participate in shared recall, exports, user models, graph discovery or dreams.
HTTP selects a view only after checking the service credential and actor scope.
"""
from __future__ import annotations

import hashlib
from .base import Store
from ..types import MemoryLayer

PRIVATE_PREFIX = "private-cli-"


def personal_primary(store):
    from .multi import MultiStore
    while isinstance(store, MultiStore):
        store = store.stores[0]
    if getattr(store, "name", "") not in ("sqlite", "postgres", "memory"):
        raise ValueError("personal memory requires a canonical private primary")
    return store


def personal_prefix(owner, actor):
    digest = hashlib.sha256((str(owner) + "\0" + str(actor)).encode()).hexdigest()
    return PRIVATE_PREFIX + digest + "-"


class PrivacyStore(Store):
    def __init__(self, store, prefix=None):
        # Human-readable Obsidian/Supabase mirrors are company-wide discovery
        # surfaces. Personal data uses the SAME canonical primary, never fanout
        # to those mirrors and never ACKs a mirror after a primary failure.
        if prefix:
            store = personal_primary(store)
        self._store = store
        self._prefix = prefix
        self.name = getattr(store, "name", "store")
        # Shared settings/session-name sidecars still resolve their existing
        # canonical SQLite path. Never delegate arbitrary backend methods.
        if not prefix and getattr(store, "path", None):
            self.path = store.path
        if not prefix and getattr(store, "stores", None):
            self.stores = [PrivacyStore(child) for child in store.stores]

    def permits(self, namespace):
        ns = str(namespace or "")
        return ns.startswith(self._prefix) if self._prefix else not ns.startswith(PRIVATE_PREFIX)

    def _assert(self, namespace):
        if not namespace or not self.permits(namespace):
            raise ValueError("memory namespace is outside the authorized scope")

    def add(self, memories):
        for memory in memories:
            self._assert(memory.namespace)
        return self._store.add(memories)

    def namespaces(self):
        return [ns for ns in self._store.namespaces() if self.permits(ns)]

    def search(self, namespace, *args, **kwargs):
        self._assert(namespace)
        return self._store.search(namespace, *args, **kwargs)

    def get(self, namespace, memory_id):
        self._assert(namespace)
        return self._store.get(namespace, memory_id)

    def delete(self, namespace, memory_id):
        self._assert(namespace)
        return self._store.delete(namespace, memory_id)

    def all(self, namespace, layers=None, with_embeddings=True):
        self._assert(namespace)
        return self._store.all(namespace, layers, with_embeddings=with_embeddings)

    def count(self, namespace, layers=None):
        self._assert(namespace)
        return self._store.count(namespace, layers)

    def timerange(self, namespace, layers=None):
        self._assert(namespace)
        return self._store.timerange(namespace, layers)

    def delete_layers(self, namespace, layers=None):
        self._assert(namespace)
        return self._store.delete_layers(namespace, layers)

    def touch(self, namespace, ids):
        self._assert(namespace)
        return self._store.touch(namespace, ids)

    def bump_importance(self, namespace, pairs):
        self._assert(namespace)
        return self._store.bump_importance(namespace, pairs)

    def change_token(self, namespace=None):
        if namespace is not None:
            self._assert(namespace)
        native = getattr(self._store, "change_token", None)
        # Opaque invalidation token; never a content or namespace enumeration.
        return native(namespace) if callable(native) else None

    def set_embeddings(self, namespace, pairs):
        self._assert(namespace)
        native = getattr(self._store, "set_embeddings", None)
        if not callable(native):
            raise RuntimeError("store does not support re-embedding")
        return native(namespace, pairs)

    def tagged(self, namespace=None, key="channel"):
        native = getattr(self._store, "tagged", None)
        rows = []
        for ns in [namespace] if namespace is not None else self.namespaces():
            self._assert(ns)
            if callable(native):
                rows.extend(native(ns, key))
        return rows

    def dimensioned(self, namespace=None):
        native = getattr(self._store, "dimensioned", None)
        rows = []
        for ns in [namespace] if namespace is not None else self.namespaces():
            self._assert(ns)
            if callable(native):
                rows.extend(native(ns))
            else:
                rows.extend((m.content, m.metadata["dimension"])
                            for m in self.all(ns, with_embeddings=False)
                            if m.content and m.metadata.get("dimension"))
        return rows

    def _aggregate_sources(self, namespace):
        if namespace is not None:
            self._assert(namespace)
            return [(namespace, 1)]
        if self._prefix:
            return [(ns, 1) for ns in self.namespaces()]
        # Preserve native GROUP BY for the large company corpus; subtract only
        # private partitions rather than scanning all company content.
        return [(None, 1)] + [(ns, -1) for ns in self._store.namespaces() if not self.permits(ns)]

    def day_counts(self, namespace=None, exclude_layers=None):
        native = getattr(self._store, "day_counts", None)
        result = {}
        if not callable(native):
            names = [namespace] if namespace is not None else self.namespaces()
            for ns in names:
                for m in self.all(ns, with_embeddings=False):
                    if m.layer.value in (exclude_layers or []) or not m.created_at:
                        continue
                    row = result.setdefault(m.created_at[:10], {"total": 0})
                    row[m.layer.value] = row.get(m.layer.value, 0) + 1
                    row["total"] += 1
            return result
        for ns, sign in self._aggregate_sources(namespace):
            for day, counts in native(ns, exclude_layers).items():
                row = result.setdefault(day, {})
                for key, count in counts.items():
                    row[key] = row.get(key, 0) + sign * count
        return {day: row for day, row in result.items() if row.get("total", 0) > 0}

    def dimension_counts(self, namespace=None):
        native = getattr(self._store, "dimension_counts", None)
        result, uncategorized = {}, 0
        if not callable(native):
            for ns in [namespace] if namespace is not None else self.namespaces():
                for m in self.all(ns, with_embeddings=False):
                    dimension, category = m.metadata.get("dimension"), m.metadata.get("category")
                    if not dimension:
                        uncategorized += 1
                        continue
                    row = result.setdefault(dimension, {"count": 0, "cats": {}})
                    row["count"] += 1
                    if category:
                        row["cats"][category] = row["cats"].get(category, 0) + 1
            return result, uncategorized
        for ns, sign in self._aggregate_sources(namespace):
            dimensions, extra = native(ns)
            uncategorized += sign * extra
            for dimension, counts in dimensions.items():
                row = result.setdefault(dimension, {"count": 0, "cats": {}})
                row["count"] += sign * counts["count"]
                for category, count in counts.get("cats", {}).items():
                    row["cats"][category] = row["cats"].get(category, 0) + sign * count
        result = {key: {"count": row["count"], "cats": {k: v for k, v in row["cats"].items() if v > 0}}
                  for key, row in result.items() if row["count"] > 0}
        return result, max(0, uncategorized)

    def bucket_counts(self):
        native = getattr(self._store, "bucket_counts", None)
        if callable(native):
            return {ns: counts for ns, counts in native().items() if self.permits(ns)}
        return {ns: {l.value: self.count(ns, [l]) for l in MemoryLayer} for ns in self.namespaces()}

    def session_stats(self, namespace=None, limit=None, offset=0):
        if namespace is not None:
            self._assert(namespace)
        # Native GROUP BY stays cheap; filter before paging, never expose a
        # private session's name/content/count through a shared __all__ query.
        rows = self._store.session_stats(namespace, None, 0)
        rows = [r for r in rows if self.permits(r.get("namespace"))]
        return rows[offset:offset + limit] if limit is not None else rows[offset:]

    def page(self, namespace=None, layers=None, limit=100, offset=0):
        return self.filter_memories(namespace, layers, limit=limit, offset=offset)

    def filter_memories(self, namespace=None, layers=None, dimension=None, category=None,
                        session=None, limit=200, offset=0, with_embeddings=False, metadata_filter=None):
        from .base import matches_filter
        names = [namespace] if namespace is not None else self.namespaces()
        native = getattr(self._store, "filter_memories", None)
        rows = []
        if namespace is None and callable(native):
            scope = dict(metadata_filter or {})
            if self._prefix:
                # Personal API supplies exact owner/actor/scope metadata; a
                # prefix check below remains defense in depth after SQL.
                if scope.get("memoryScope") != "personal" or not scope.get("actorId"):
                    raise ValueError("personal metadata scope required")
            else:
                previous = scope.get("$not", [])
                scope["$not"] = (previous if isinstance(previous, list) else [previous]) + [{"memoryScope": "personal"}]
            return [m for m in native(None, layers, dimension, category, session,
                                     limit, offset, with_embeddings, scope)
                    if self.permits(m.namespace)]
        for ns in names:
            self._assert(ns)
            if callable(native):
                rows.extend(native(ns, layers, dimension, category, session,
                                   limit + offset, 0, with_embeddings, metadata_filter))
            else:
                for memory in self.all(ns, layers, with_embeddings):
                    md = memory.metadata or {}
                    if (dimension and md.get("dimension") != dimension
                            or category and md.get("category") != category
                            or session and md.get("session") != session
                            or not matches_filter(memory, metadata_filter)):
                        continue
                    rows.append(memory)
        rows.sort(key=lambda m: m.created_at or "", reverse=True)
        return rows[offset:offset + limit]

    def day(self, namespace=None, date=None, layers=None, with_embeddings=False):
        names = [namespace] if namespace is not None else self.namespaces()
        rows = []
        for ns in names:
            self._assert(ns)
            native = getattr(self._store, "day", None)
            rows.extend(native(ns, date, layers, with_embeddings) if callable(native) else
                        [m for m in self.all(ns, layers, with_embeddings)
                         if not date or (m.created_at or "").startswith(date)])
        return rows

    def mentions(self, namespace, name, limit=0, with_embeddings=False):
        self._assert(namespace)
        native = getattr(self._store, "mentions", None)
        if callable(native):
            return native(namespace, name, limit=limit, with_embeddings=with_embeddings)
        rows = [m for m in self.all(namespace, with_embeddings=with_embeddings)
                if str(name).lower() in str(m.content).lower()]
        return rows[:limit] if limit else rows
