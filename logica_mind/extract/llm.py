"""LLM extractor: atomic facts + add/update/noop reconciliation.

Given a message and the most relevant existing memories, the LLM returns a list
of facts, each tagged ADD (new), UPDATE (supersedes an existing memory by id) or
NOOP (already known). Falls back to NoopExtractor behavior if no LLM is available
or the reply can't be parsed.
"""
from __future__ import annotations

import sys

from typing import List, Optional

from ..types import Memory
from ..llm.base import LLM, NullLLM
from .base import Extractor, Fact, ExtractOp
from .noop import NoopExtractor
from .taxonomy import prompt_guidance, DIM_IDS

_SYSTEM = (
    "You extract durable, atomic facts from a message for a long-term memory store. "
    "Return ONLY JSON: a list of objects with keys "
    '"content" (the fact, self-contained, third person), '
    '"category" (a short 1-3 word topical label you coin, e.g. "Coffee preference", "Zodiac sign", "Career goal"), '
    '"dimension" (the single best life-dimension id from the list below), '
    '"op" (one of "add", "update", "delete", "noop"), '
    '"target_id" (id of the existing memory to act on for "update"/"delete", else null), '
    '"importance" (0..1). '
    'Use "update" when a new fact supersedes an existing memory (set target_id). '
    'Use "delete" when an existing memory is now FALSE or retracted and has no replacement (set target_id). '
    'Use "noop" if the fact is already represented in existing memories. '
    "Extract only meaningful, lasting facts — skip greetings, filler and transient chatter. "
    "Be thorough: a single sentence often carries several facts across different dimensions. "
    "If the message contains no durable fact, return [].\n\n"
    + prompt_guidance()
)
_DIMS = set(DIM_IDS)


class LLMExtractor(Extractor):
    name = "llm"

    def __init__(self, llm: LLM, max_existing: int = 12, system: Optional[str] = None,
                 strict: bool = False):
        self.llm = llm or NullLLM()
        self.max_existing = max_existing
        self.system = system or _SYSTEM
        self._fallback = NoopExtractor()
        # strict=True: when the LLM WAS available but its reply fails (raises or
        # isn't a JSON list), return [] instead of NoopExtractor's whole-text Fact.
        # Used for conversation ingestion so a parse failure never dumps the raw
        # multi-turn transcript into the semantic layer as one "fact".
        self.strict = strict

    def extract(self, text: str, existing: List[Memory]) -> List[Fact]:
        text = (text or "").strip()
        if not text:
            return []
        if not getattr(self.llm, "available", False):
            return self._fallback.extract(text, existing)   # legit offline path

        existing_block = "\n".join(
            f"- [{m.id}] {m.content}" for m in existing[: self.max_existing]
        ) or "(none)"
        prompt = (
            f"EXISTING MEMORIES:\n{existing_block}\n\n"
            f"NEW MESSAGE:\n{text}\n\n"
            "Extract the facts as JSON."
        )
        try:
            data = self.llm.complete_json(prompt, system=self.system)
        except Exception as e:  # network/parse issues shouldn't lose the write
            print(f"[logica-mind] LLMExtractor fell back ({e})", file=sys.stderr)
            return [] if self.strict else self._fallback.extract(text, existing)

        if not isinstance(data, list):
            return [] if self.strict else self._fallback.extract(text, existing)

        facts: List[Fact] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                op = ExtractOp(item.get("op", "add"))
            except ValueError:
                op = ExtractOp.ADD
            if op == ExtractOp.NOOP:
                continue
            content = (item.get("content") or "").strip()
            target_id = item.get("target_id") or None

            if op == ExtractOp.DELETE:
                if not target_id:        # a delete needs something to delete
                    continue
                facts.append(Fact(content=content or "(retracted)", op=op, target_id=target_id))
                continue
            if not content:
                continue
            cat = (item.get("category") or "").strip() or None
            dim = (item.get("dimension") or "").strip().lower() or None
            if dim and dim not in _DIMS:
                dim = None
            facts.append(
                Fact(
                    content=content,
                    op=op,
                    target_id=target_id,
                    importance=float(item.get("importance", 0.5) or 0.5),
                    category=cat,
                    dimension=dim,
                )
            )
        return facts
