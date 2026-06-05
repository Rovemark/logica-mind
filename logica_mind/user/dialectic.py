"""Dialectic user model.

Keeps a living "theory of the user": raw observations accumulate, and a
synthesis step reconciles them into one concise profile. With an LLM the
synthesis is genuinely dialectic (it reasons about who the user is); without one
it degrades to a de-duplicated list of observations. The profile is stored as a
single USER-layer memory so it travels through the same stores as everything else.
"""
from __future__ import annotations

import sys

from typing import List, Optional

from ..types import Memory, MemoryLayer
from ..stores.base import Store
from ..embeddings.base import Embedder
from ..llm.base import LLM, NullLLM

_SYSTEM = (
    "You maintain a concise, evolving model of a user for an AI assistant. "
    "Given the CURRENT MODEL and NEW OBSERVATIONS, return an updated model in plain "
    "prose with short labelled lines (Identity, Preferences, Communication style, "
    "Goals, Context). Reconcile contradictions in favour of the most recent "
    "observation. Be specific and brief. Return only the updated model text."
)

_QUERY_SYSTEM = (
    "You answer a question ABOUT a user for an AI assistant, reasoning from the "
    "user model and observations provided. Ground every claim in them. If the "
    "answer isn't supported, say what is unknown rather than guessing. Be concise."
)


class DialecticUserModel:
    def __init__(
        self,
        store: Store,
        namespace: str,
        llm: Optional[LLM] = None,
        embedder: Optional[Embedder] = None,
        synth_system: Optional[str] = None,
        query_system: Optional[str] = None,
    ):
        self.store = store
        self.namespace = namespace
        self.llm = llm or NullLLM()
        self.embedder = embedder
        self.synth_system = synth_system or _SYSTEM
        self.query_system = query_system or _QUERY_SYSTEM
        self._profile_id = f"user-profile::{namespace}"

    # ---- observations ------------------------------------------------------
    def observe(self, text: str, importance: float = 0.6) -> Optional[Memory]:
        text = (text or "").strip()
        if not text:
            return None
        m = Memory(
            content=text,
            namespace=self.namespace,
            layer=MemoryLayer.USER,
            importance=importance,
            tags=["observation"],
        )
        if self.embedder is not None:
            m.embedding = self.embedder.embed_one(text)
        self.store.add([m])
        return m

    def _observations(self) -> List[Memory]:
        obs = [
            m for m in self.store.all(self.namespace, layers=[MemoryLayer.USER])
            if "observation" in (m.tags or [])
        ]
        # store.all() order is backend-defined; sort so the obs[-N:] slices in
        # profile()/synthesize() really take the NEWEST observations
        obs.sort(key=lambda m: m.created_at or "")
        return obs

    # ---- profile -----------------------------------------------------------
    def profile(self) -> str:
        m = self.store.get(self.namespace, self._profile_id)
        if m:
            return m.content
        # no synthesized profile yet → fall back to raw observations
        obs = self._observations()
        return "\n".join(f"- {o.content}" for o in obs[-12:])

    def synthesize(self) -> str:
        """The dialectic step. Reconcile observations into one profile. Also run
        during dreaming."""
        obs = self._observations()
        if not obs:
            return ""
        current = ""
        existing = self.store.get(self.namespace, self._profile_id)
        if existing:
            current = existing.content

        if getattr(self.llm, "available", False):
            new_obs = "\n".join(f"- {o.content}" for o in obs[-30:])
            prompt = f"CURRENT MODEL:\n{current or '(empty)'}\n\nNEW OBSERVATIONS:\n{new_obs}"
            try:
                text = self.llm.complete(prompt, system=self.synth_system).strip()
            except Exception as e:
                print(f"[logica-mind] user synthesize fell back ({e})", file=sys.stderr)
                text = self._join_observations(obs)
        else:
            text = self._join_observations(obs)

        profile = Memory(
            id=self._profile_id,
            content=text,
            namespace=self.namespace,
            layer=MemoryLayer.USER,
            importance=0.9,
            tags=["profile"],
        )
        if self.embedder is not None:
            profile.embedding = self.embedder.embed_one(text)
        self.store.add([profile])
        return text

    def query(self, question: str, k: int = 8) -> str:
        """Dialectic query: answer a question ABOUT the user,
        reasoning over the profile + relevant observations. With an LLM it
        reasons; without one it returns the most relevant facts."""
        question = (question or "").strip()
        if not question:
            return ""
        profile = self.profile()
        q_emb = None
        if self.embedder is not None:
            try:
                q_emb = self.embedder.embed_query(question)
            except Exception:
                q_emb = None
        # exclude the synthesized profile (already supplied as USER MODEL) so it
        # isn't fed twice and doesn't crowd out atomic observations
        hits = [
            h for h in self.store.search(self.namespace, q_emb, question, [MemoryLayer.USER], k + 1)
            if h.memory.id != self._profile_id and "observation" in (h.memory.tags or [])
        ][:k]
        facts = "\n".join(f"- {h.memory.content}" for h in hits)

        if getattr(self.llm, "available", False):
            prompt = (
                f"USER MODEL:\n{profile or '(empty)'}\n\n"
                f"RELEVANT OBSERVATIONS:\n{facts or '(none)'}\n\n"
                f"QUESTION: {question}"
            )
            try:
                return self.llm.complete(prompt, system=self.query_system).strip()
            except Exception as e:
                print(f"[logica-mind] dialectic query fell back ({e})", file=sys.stderr)
        # no LLM (or failure): return the grounding material itself
        return facts or profile or ""

    @staticmethod
    def _join_observations(obs: List[Memory]) -> str:
        seen, lines = set(), []
        for o in obs:
            key = " ".join((o.content or "").lower().split())   # collapse internal whitespace too
            if not key or key in seen:
                continue
            seen.add(key)
            lines.append(f"- {o.content.strip()}")
        return "\n".join(lines)
