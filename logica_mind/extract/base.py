"""Extractor interface — turns raw text into atomic, de-duplicated facts.

This is the Mem0-style layer: instead of storing whole paragraphs, an extractor
decides what discrete facts a message contains and whether each one is new,
updates an existing memory, or is redundant.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from ..types import Memory


class ExtractOp(str, Enum):
    ADD = "add"        # a brand-new fact
    UPDATE = "update"  # supersedes an existing memory (see target_id)
    DELETE = "delete"  # an existing memory is now false; remove it (see target_id)
    NOOP = "noop"      # already known; ignore


@dataclass
class Fact:
    content: str
    op: ExtractOp = ExtractOp.ADD
    target_id: Optional[str] = None   # set when op == UPDATE or DELETE
    importance: float = 0.5
    tags: List[str] = field(default_factory=list)


class Extractor(ABC):
    name: str = "extractor"

    @abstractmethod
    def extract(self, text: str, existing: List[Memory]) -> List[Fact]:
        """Return the facts contained in `text`, reconciled against `existing`."""
