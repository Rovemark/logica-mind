"""LangChain memory adapter.

Drop Logica Mind in as a LangChain memory: it recalls relevant long-term memory
for the current input and persists each turn. Implements the BaseMemory method
surface (memory_variables / load_memory_variables / save_context / clear) by duck
typing, so this module imports with or without LangChain installed. For strict
pydantic validation, subclass langchain_core.memory.BaseMemory and delegate here.

    from logica_mind import LogicaMind
    from logica_mind.integrations.langchain import LogicaMindMemory
    memory = LogicaMindMemory(LogicaMind(namespace="agent"))
"""
from __future__ import annotations

from typing import Any, Dict, List


class LogicaMindMemory:
    def __init__(self, mind, memory_key: str = "history", input_key: str = "input",
                 output_key: str = "output", limit: int = 6,
                 distil: bool = True, distil_every: int = 1):
        self.mind = mind
        self.memory_key = memory_key
        self.input_key = input_key
        self.output_key = output_key
        self.limit = limit
        # LLM fact-extraction on the user turn is the expensive part. distil=False
        # turns it off (raw turns still logged); distil_every=N runs it only every
        # Nth turn so a chatty loop doesn't fire one LLM call per message.
        self.distil = distil
        self.distil_every = max(1, int(distil_every))
        self._turns = 0

    @property
    def memory_variables(self) -> List[str]:
        return [self.memory_key]

    def load_memory_variables(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        query = str(inputs.get(self.input_key, "") or "")
        hits = self.mind.recall(query, limit=self.limit) if query else []
        text = "\n".join(f"- {h.memory.content}" for h in hits)
        return {self.memory_key: text}

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        user = str(inputs.get(self.input_key, "") or "")
        ai = str(outputs.get(self.output_key) or next(iter(outputs.values()), "") or "")
        if user:
            self.mind.log(user, role="user")
            self._turns += 1
            if self.distil and (self._turns % self.distil_every == 0):
                self.mind.remember(user)      # distil durable facts from the user turn
        if ai:
            self.mind.log(ai, role="assistant")

    def clear(self) -> None:
        # clear this namespace's episodic turns (keep distilled knowledge) in one
        # bulk delete instead of one round-trip per row
        from ..types import MemoryLayer
        self.mind.store.delete_layers(self.mind.namespace, [MemoryLayer.EPISODIC])
