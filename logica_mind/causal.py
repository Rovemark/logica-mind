"""Causal world-model over the temporal knowledge graph.

The temporal graph already stores facts as (subject, predicate, object) edges with a
confidence and temporal validity. A CAUSAL edge is simply an edge whose predicate denotes
causation ('causa', 'leva_a', 'resulta_em', 'previne', 'causes', 'leads_to', ...). This
layer READS those edges to answer the questions a memory album cannot — the leap from
"remembers facts" to "predicts and acts":

    predict(x)   → what does x likely CAUSE?              ("se X, provavelmente Y")
    causes(y)    → what likely CAUSED y?                  ("por que Y? por causa de X")
    chain(x, d)  → 2nd/3rd-order consequences of x        ("X → Y → Z", segunda ordem)

READ-ONLY over the graph: the causal knowledge lives in the SAME edges the extractor and
the dream already produce (anti-redundância — nasce em cima do que existe). Zero third-party
dependency (stdlib only), fiel ao núcleo do logica-mind.
"""
from __future__ import annotations

from typing import Dict, List, Optional

# Raízes causais (pt + en). O predicado do extractor é snake_case livre → casamos por
# SUBSTRING pra tolerar variações ('causa', 'causou', 'leva_a_churn', 'resulted_in', ...).
_CAUSE_ROOTS = (
    "causa", "causou", "causar", "causando",
    "leva_a", "levou_a", "levar_a", "leva", "levando",
    "resulta", "resultou", "resultar",
    "provoca", "provocou", "provocar",
    "gera", "gerou", "gerar", "gerando",
    "aumenta", "aumentou", "aumentar",
    "reduz", "reduziu", "reduzir", "diminui", "diminuiu",
    "impacta", "impactou", "afeta", "afetou",
    "possibilita", "permite", "permitiu", "habilita",
    "desencadeia", "dispara", "disparou",
    "previne", "preveniu", "prevenir", "evita", "evitou", "bloqueia", "bloqueou",
    # english
    "cause", "causes", "caused", "causing",
    "lead_to", "leads_to", "led_to",
    "result", "results_in", "resulted_in",
    "trigger", "triggers", "triggered",
    "increase", "increases", "reduce", "reduces",
    "prevent", "prevents", "enable", "enables",
    "drive", "drives", "impact", "impacts", "affect", "affects", "worsen", "improve",
)
# Predicados de efeito NEGATIVO (o "efeito" é a AUSÊNCIA/redução do object).
_INHIBIT = (
    "previne", "preveniu", "prevenir", "evita", "evitou", "bloqueia", "bloqueou",
    "reduz", "reduziu", "reduzir", "diminui", "diminuiu",
    "prevent", "prevents", "reduce", "reduces", "block", "blocks", "worsen",
)


def is_causal(predicate: str) -> bool:
    """True se o predicado denota causação."""
    p = (predicate or "").lower()
    return any(root in p for root in _CAUSE_ROOTS)


def _polarity(predicate: str) -> str:
    p = (predicate or "").lower()
    return "inhibits" if any(r in p for r in _INHIBIT) else "promotes"


class CausalModel:
    """Raciocínio causal read-only sobre um TemporalGraph."""

    def __init__(self, graph):
        self.g = graph

    def _causal_edges(self, at: Optional[str] = None):
        return [e for e in self.g.edges(at=at) if is_causal(e.predicate)]

    @staticmethod
    def _conf(e) -> float:
        c = getattr(e, "confidence", None)
        try:
            return float(c) if c is not None else 0.5
        except (TypeError, ValueError):
            return 0.5

    def predict(self, cause: str, at: Optional[str] = None, min_conf: float = 0.0) -> List[Dict]:
        """O que `cause` provavelmente CAUSA (efeitos diretos), ranqueado por confiança."""
        c = self.g.resolve(cause).lower()
        out: List[Dict] = []
        for e in self._causal_edges(at):
            if e.subject.lower() == c:
                conf = self._conf(e)
                if conf < min_conf:
                    continue
                out.append({
                    "effect": e.object, "predicate": e.predicate,
                    "polarity": _polarity(e.predicate),
                    "confidence": round(conf, 3), "since": e.valid_from,
                })
        out.sort(key=lambda x: x["confidence"], reverse=True)
        return out

    def causes(self, effect: str, at: Optional[str] = None) -> List[Dict]:
        """O que provavelmente CAUSOU `effect` (traversal backward — a explicação)."""
        eff = self.g.resolve(effect).lower()
        out: List[Dict] = []
        for e in self._causal_edges(at):
            if e.object.lower() == eff:
                out.append({
                    "cause": e.subject, "predicate": e.predicate,
                    "polarity": _polarity(e.predicate),
                    "confidence": round(self._conf(e), 3), "since": e.valid_from,
                })
        out.sort(key=lambda x: x["confidence"], reverse=True)
        return out

    def chain(self, cause: str, depth: int = 2, at: Optional[str] = None, min_conf: float = 0.15) -> Dict:
        """Consequências de 2ª/3ª ordem: X → Y → Z. A confiança do CAMINHO é o produto das
        confianças das arestas (decai com a distância — incerteza acumula). BFS com anti-ciclo."""
        depth = max(1, min(4, int(depth)))
        root = self.g.resolve(cause)
        nodes: Dict[str, Dict] = {root.lower(): {"name": root, "depth": 0, "path_confidence": 1.0}}
        links: List[Dict] = []
        seen_edges = set()
        frontier = [(root, 1.0, 0)]
        while frontier:
            node, pconf, d = frontier.pop(0)
            if d >= depth:
                continue
            for step in self.predict(node, at=at):
                path_conf = pconf * step["confidence"]
                if path_conf < min_conf:
                    continue
                eff = step["effect"]
                ek = (node.lower(), eff.lower(), step["predicate"])
                if ek in seen_edges:
                    continue
                seen_edges.add(ek)
                links.append({
                    "from": node, "to": eff, "predicate": step["predicate"],
                    "polarity": step["polarity"], "confidence": step["confidence"],
                    "path_confidence": round(path_conf, 3), "order": d + 1,
                })
                k = eff.lower()
                if k not in nodes or nodes[k]["path_confidence"] < path_conf:
                    nodes[k] = {"name": eff, "depth": d + 1, "path_confidence": round(path_conf, 3)}
                frontier.append((eff, path_conf, d + 1))
        return {
            "cause": root,
            "nodes": sorted(nodes.values(), key=lambda n: (n["depth"], -n["path_confidence"])),
            "links": links,
            "second_order": [l for l in links if l["order"] >= 2],
        }

    def summary(self, at: Optional[str] = None) -> Dict:
        ce = self._causal_edges(at)
        promotes = sum(1 for e in ce if _polarity(e.predicate) == "promotes")
        return {
            "causal_edges": len(ce),
            "promotes": promotes,
            "inhibits": len(ce) - promotes,
            "total_edges": len(self.g.edges(at=at)),
        }
