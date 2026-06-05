"""Embedding providers. The default (HashingEmbedder) needs no API key."""
from .base import Embedder
from .hashing import HashingEmbedder
from .batched import BatchedEmbedder

__all__ = ["Embedder", "HashingEmbedder", "BatchedEmbedder", "VoyageEmbedder",
           "OpenAIEmbedder", "LocalEmbedder", "VoyageMultimodalEmbedder"]


def __getattr__(name):
    # lazy so importing the package never pulls optional deps
    if name == "VoyageEmbedder":
        from .voyage import VoyageEmbedder
        return VoyageEmbedder
    if name == "OpenAIEmbedder":
        from .openai import OpenAIEmbedder
        return OpenAIEmbedder
    if name == "LocalEmbedder":
        from .local import LocalEmbedder
        return LocalEmbedder
    if name == "VoyageMultimodalEmbedder":
        from .multimodal import VoyageMultimodalEmbedder
        return VoyageMultimodalEmbedder
    raise AttributeError(name)
