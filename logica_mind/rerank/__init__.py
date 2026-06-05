"""Rerankers — the final relevance pass over recall candidates.

MMRReranker is offline (diversity); VoyageReranker is a cross-encoder (quality).
"""
from .base import Reranker
from .mmr import MMRReranker
from .graph import NodeDistanceReranker, EpisodeMentionReranker
from .rrf import RRFReranker

__all__ = ["Reranker", "MMRReranker", "NodeDistanceReranker",
           "EpisodeMentionReranker", "RRFReranker", "VoyageReranker"]


def __getattr__(name):
    if name == "VoyageReranker":
        from .voyage import VoyageReranker
        return VoyageReranker
    raise AttributeError(name)
