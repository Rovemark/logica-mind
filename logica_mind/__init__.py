"""Logica Mind — pluggable, multi-store memory for any AI system.

Quickstart (no API keys needed):

    from logica_mind import LogicaMind
    mind = LogicaMind(namespace="my-agent")
    mind.remember("The user prefers concise answers in Portuguese.")
    for hit in mind.recall("what language should I use?"):
        print(hit.score, hit.memory.content)
"""
from .core import LogicaMind
from .types import Memory, MemoryLayer, SearchResult

__version__ = "0.2.26"

__all__ = ["LogicaMind", "Memory", "MemoryLayer", "SearchResult", "__version__"]
