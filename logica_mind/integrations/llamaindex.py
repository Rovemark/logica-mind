"""LlamaIndex memory adapter.

Implements the LlamaIndex BaseMemory method surface (put / get / get_all / set /
reset) by duck typing, mapping chat turns onto Logica Mind. Imports with or
without LlamaIndex installed.

    from logica_mind import LogicaMind
    from logica_mind.integrations.llamaindex import LogicaMindMemory
    memory = LogicaMindMemory(LogicaMind(namespace="agent"))
"""
from __future__ import annotations

from typing import Any, List, Optional


class LogicaMindMemory:
    def __init__(self, mind, limit: int = 8):
        self.mind = mind
        self.limit = limit

    def put(self, message: Any) -> None:
        if isinstance(message, dict):
            raw_role, content = message.get("role", "user"), message.get("content")
        elif hasattr(message, "content"):
            raw_role, content = getattr(message, "role", None) or "user", getattr(message, "content", None)
        else:
            raw_role, content = "user", str(message)
        if not content:
            return                              # skip empty turns (don't store repr)
        # normalize MessageRole enum / 'USER' → 'user'
        role = str(getattr(raw_role, "value", raw_role) or "user").lower()
        self.mind.log(str(content), role=role)
        if role in ("user", "human"):
            self.mind.remember(str(content))

    def get(self, input: Optional[str] = None, **kwargs) -> List[dict]:
        if not input:
            return []
        return [{"role": "system", "content": f"- {h.memory.content}"}
                for h in self.mind.recall(input, limit=self.limit)]

    def get_all(self) -> List[dict]:
        from ..types import MemoryLayer
        rows = self.mind.store.all(self.mind.namespace, [MemoryLayer.EPISODIC])
        rows.sort(key=lambda m: m.created_at or "")
        return [{"role": (m.metadata or {}).get("role", "user"), "content": m.content} for m in rows]

    def set(self, messages: List[Any]) -> None:
        for msg in messages:
            self.put(msg)

    def reset(self) -> None:
        from ..types import MemoryLayer
        for m in self.mind.store.all(self.mind.namespace, [MemoryLayer.EPISODIC]):
            self.mind.forget(memory_id=m.id)
