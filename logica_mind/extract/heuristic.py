"""Offline heuristic extractor — fact tagging WITHOUT an LLM.

The no-key default used to be a pure noop: facts were stored raw, with no
dimension/category, so a zero-config client got an empty Profile and a grey
graph. This extractor keeps `remember()` LLM-free but votes a life/work
DIMENSION per fact from keyword evidence:

  • the taxonomy's own example categories + labels (extract.taxonomy.DIMENSIONS)
    become the keyword index — single source of truth, no duplicated lists;
  • a compact Portuguese supplement covers the most common pt-BR words (the
    taxonomy examples are English);
  • single-word keywords match on token boundaries (no 'AI' inside 'rain');
    multi-word keywords match as substrings.

It is intentionally conservative: no votes → no dimension (exactly the old
behaviour), never a wrong-looking guess from one weak signal alone. An LLM
upgrade later re-categorizes via the dreaming cycle.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from ..types import Memory
from .base import Extractor, Fact, ExtractOp
from .taxonomy import DIMENSIONS

# pt-BR supplement: common words → dimension id (the taxonomy examples are EN)
_PT: Dict[str, str] = {
    "saúde": "health", "dieta": "health", "treino": "health", "sono": "health",
    "remédio": "health", "alergia": "health",
    "cidade": "location", "bairro": "location", "mora": "location", "morar": "location",
    "aniversário": "time", "rotina": "time", "agenda": "time", "horário": "time",
    "gosto": "preference", "prefiro": "preference", "favorito": "preference",
    "odeio": "preference", "adoro": "preference",
    "família": "relationship", "amigo": "relationship", "esposa": "relationship",
    "marido": "relationship", "filho": "relationship", "filha": "relationship",
    "meta": "ambition", "sonho": "ambition", "objetivo": "ambition",
    "fé": "spirituality", "oração": "spirituality", "igreja": "spirituality",
    "hábito": "habit", "costume": "habit",
    "carro": "possession", "casa": "possession", "apartamento": "possession",
    "carreira": "career", "emprego": "career", "trabalho": "career", "cargo": "career",
    "salário": "personal_finance", "dinheiro": "personal_finance", "poupança": "personal_finance",
    "projeto": "project_status", "entrega": "project_status", "lançamento": "project_status",
    "prazo": "project_timeline", "cronograma": "project_timeline",
    "risco": "project_risk", "bloqueio": "project_risk", "bug": "project_risk",
    "equipe": "org_team", "time": "org_team", "contratação": "org_team",
    "produto": "org_product", "mercado": "org_market", "concorrente": "org_market",
    "estratégia": "org_strategy", "cliente": "org_customer", "parceria": "org_partnership",
    "receita": "biz_revenue", "faturamento": "biz_revenue", "vendas": "biz_revenue",
    "custo": "biz_cost", "despesa": "biz_cost",
    "investimento": "biz_funding", "captação": "biz_funding",
    "preço": "biz_pricing", "desconto": "biz_pricing",
    "métrica": "biz_metric", "contrato": "biz_legal", "jurídico": "biz_legal",
}

_WORD = re.compile(r"[\wÀ-ÿ][\wÀ-ÿ'\-]*")


def _build_index() -> Dict[str, str]:
    """keyword(lower) → dimension id, from the taxonomy itself + the PT supplement."""
    idx: Dict[str, str] = {}
    for d in DIMENSIONS:
        for kw in d.get("examples", []) + [d["label"]]:
            kw = str(kw).strip().lower()
            if len(kw) >= 3:
                idx.setdefault(kw, d["id"])
    for kw, dim in _PT.items():
        idx.setdefault(kw, dim)
    return idx


_INDEX = _build_index()
_SINGLE = {k: v for k, v in _INDEX.items() if " " not in k}
_MULTI = {k: v for k, v in _INDEX.items() if " " in k}


def guess_dimension(text: str) -> Optional[str]:
    """Majority-vote a dimension for `text` from keyword evidence (None = no vote)."""
    low = (text or "").lower()
    if not low.strip():
        return None
    votes: Dict[str, int] = {}
    toks = set(_WORD.findall(low))
    for kw, dim in _SINGLE.items():
        if kw in toks:
            votes[dim] = votes.get(dim, 0) + 1
    for kw, dim in _MULTI.items():
        if kw in low:
            votes[dim] = votes.get(dim, 0) + 2     # multi-word evidence is stronger
    if not votes:
        return None
    return max(votes, key=lambda d: votes[d])


class HeuristicExtractor(Extractor):
    """The zero-key default: stores the text as one fact (like noop did) but with
    a keyword-voted dimension, so offline clients get a living Profile and a
    coloured graph out of the box."""
    name = "heuristic"

    def extract(self, text: str, existing: List[Memory]) -> List[Fact]:
        text = (text or "").strip()
        if not text:
            return []
        dim = guess_dimension(text)
        return [Fact(content=text, op=ExtractOp.ADD, dimension=dim)]
