"""Fact extraction. Default NoopExtractor needs no LLM."""
from .base import Extractor, Fact, ExtractOp
from .noop import NoopExtractor
from .llm import LLMExtractor
from .heuristic import HeuristicExtractor

__all__ = ["Extractor", "Fact", "ExtractOp", "NoopExtractor", "LLMExtractor", "HeuristicExtractor"]
