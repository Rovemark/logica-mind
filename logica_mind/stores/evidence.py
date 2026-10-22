"""A narrowly scoped view for graph consolidation, never a separate store."""
from .base import matches_filter


class EvidenceStore:
    def __init__(self, store, scope):
        self.store, self.scope = store, dict(scope)

    def all(self, namespace, layers=None, with_embeddings=True):
        return [m for m in self.store.all(namespace, layers, with_embeddings=with_embeddings)
                if matches_filter(m, self.scope)]

    def get(self, namespace, memory_id):
        m = self.store.get(namespace, memory_id)
        return m if m and matches_filter(m, self.scope) else None

    def add(self, memories):
        for memory in memories:
            # IDs can be supplied by graph operations. Never overwrite another
            # partition even if an internal caller carries a stale foreign ID.
            previous = self.store.get(memory.namespace, memory.id)
            if previous and not matches_filter(previous, self.scope):
                raise ValueError('graph evidence scope mismatch')
            md = dict(memory.metadata or {})
            if any(k in md and md[k] != v for k, v in self.scope.items()):
                raise ValueError('graph evidence scope mismatch')
            memory.metadata = {**md, **self.scope}
        return self.store.add(memories)
