"""Tiny pure-Python vector helpers.

No numpy: keeps the core dependency-free. Fine for the volumes a single-process
memory layer deals with; stores that need scale (Supabase/pgvector) push the math
into the database instead.
"""
from __future__ import annotations

import math
from typing import List, Sequence


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def norm(a: Sequence[float]) -> float:
    return math.sqrt(sum(x * x for x in a))


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity in [-1, 1] (0 if either vector is empty/zero).

    Returns 0.0 on a dimension mismatch instead of silently truncating via
    zip() — this prevents the classic footgun of mixing vectors from two
    different embedders (e.g. 256-d hashing vs 1024-d Voyage) producing garbage
    similarities. The core warns when it detects such a mismatch."""
    if not a or not b or len(a) != len(b):
        return 0.0
    na, nb = norm(a), norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot(a, b) / (na * nb)


def l2_normalize(a: Sequence[float]) -> List[float]:
    n = norm(a)
    if n == 0.0:
        return list(a)
    return [x / n for x in a]


def recency_score(age_seconds: float, half_life_days: float = 7.0) -> float:
    """Ebbinghaus-style decay in (0, 1]. 1.0 = brand new."""
    if age_seconds <= 0:
        return 1.0
    half_life = half_life_days * 86400.0
    return 0.5 ** (age_seconds / half_life)
