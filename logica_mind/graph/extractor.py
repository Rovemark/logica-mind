"""LLM graph extraction — turn prose into (subject, predicate, object) triples.

This is what lets the GRAPH layer build itself automatically instead of
requiring manual graph.ingest() calls. Needs an LLM; with none it returns nothing
(the graph simply stays manual). Feed the triples to TemporalGraph.ingest so they
get temporal validity + invalidation like any other edge.
"""
from __future__ import annotations

import sys

from dataclasses import dataclass
from typing import List, Optional

from ..llm.base import LLM, NullLLM

_SYSTEM = (
    "You extract factual relationships from text as a JSON list of triples. "
    "Each item: {\"subject\": entity, \"predicate\": short_relation_in_snake_case, "
    "\"object\": entity_or_value, \"fact\": one self-contained sentence, "
    "\"confidence\": number 0..1, "
    "\"subject_type\": entity category (Person/Organization/Place/Product/Concept), "
    "\"object_type\": entity category}. "
    "Entities are people, organizations, places, products or concepts. "
    "confidence reflects how certain the relation is from the text. "
    "Extract only durable, factual relations — skip opinions, greetings and filler. "
    "Return [] if there is no factual relation."
)


@dataclass
class Triple:
    subject: str
    predicate: str
    object: str
    fact: str = ""
    confidence: float = 1.0
    subject_type: str = ""
    object_type: str = ""


class GraphExtractor:
    name = "graph-extractor"

    def __init__(self, llm: Optional[LLM] = None, system: Optional[str] = None):
        self.llm = llm or NullLLM()
        self.system = system or _SYSTEM

    @property
    def available(self) -> bool:
        return getattr(self.llm, "available", False)

    def extract(self, text: str) -> List[Triple]:
        text = (text or "").strip()
        if not text or not self.available:
            return []
        try:
            data = self.llm.complete_json(f"TEXT:\n{text}\n\nExtract the triples as JSON.", system=self.system)
        except Exception as e:
            print(f"[logica-mind] GraphExtractor failed ({e})", file=sys.stderr)
            return []
        if isinstance(data, dict):
            # LLMs often wrap the array, e.g. {"triples": [...]} / {"relations": [...]}
            unwrapped = None
            for key in ("triples", "relations", "facts", "items", "data"):
                v = data.get(key)
                if isinstance(v, list):
                    unwrapped = v
                    break
            if unwrapped is None:
                unwrapped = next((v for v in data.values() if isinstance(v, list)), None)
            data = unwrapped
        if not isinstance(data, list):
            return []
        out: List[Triple] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            # coerce to str: the prompt allows object to be an "entity_or_value",
            # so a non-string (int/bool) must not crash .strip()
            s = str(item.get("subject") or "").strip()
            p = str(item.get("predicate") or "").strip()
            o = str(item.get("object") or "").strip()
            if not (s and p and o):
                continue
            try:
                conf = float(item.get("confidence", 1.0))
            except (TypeError, ValueError):
                conf = 1.0
            conf = max(0.0, min(1.0, conf))
            out.append(Triple(
                subject=s, predicate=p, object=o,
                fact=str(item.get("fact") or "").strip(), confidence=conf,
                subject_type=str(item.get("subject_type") or "").strip(),
                object_type=str(item.get("object_type") or "").strip(),
            ))
        return out
