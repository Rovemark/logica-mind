"""Fact extraction. Default NoopExtractor needs no LLM."""
from .base import Extractor, Fact, ExtractOp
from .noop import NoopExtractor
from .llm import LLMExtractor

__all__ = ["Extractor", "Fact", "ExtractOp", "NoopExtractor", "LLMExtractor"]
