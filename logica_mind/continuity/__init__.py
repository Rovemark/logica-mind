"""Continuity substrate — the organs that turn *memory you query* into *memory
you are*: a versioned self-model, a cognitive heartbeat, a shared cortex of
insights, metacognition and consequential debate.

Each organ is dependency-injected (it receives a ``store`` and friends) and
imports nothing outside ``logica_mind`` — so it stays a clean, embeddable kernel.

Phase -1 ships :class:`SelfModel` (versioned, hash-chained, atomic, restorable).
:class:`Heartbeat` adds the cognitive cycle on top. The rest lands in later phases.
"""
from .heartbeat import Heartbeat, beat_all
from .self_model import SelfModel

__all__ = ["SelfModel", "Heartbeat", "beat_all"]
