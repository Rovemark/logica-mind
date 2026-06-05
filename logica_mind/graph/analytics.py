"""Graph analytics — pure functions over an entity graph.

These power the dashboard's intelligence: importance (PageRank) for node sizing,
a 6-class predicate taxonomy for edge colour, shortest-path "how is A related to
B?", structural bridges, and link prediction. All standard-library, no embedder
required (semantic helpers live in core where the vectors are).
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Dict, Iterable, List, Optional, Tuple


# ---- predicate taxonomy ----------------------------------------------------
# six broad classes so the canvas can hue an edge by the KIND of relation, not
# just draw every relation the same blue. Matched on substrings of the predicate.
_PCLASS_RULES: List[Tuple[str, tuple]] = [
    ("social", ("works", "report", "manage", "lead", "found", "member", "partner",
                "friend", "knows", "married", "collaborat", "invest", "hire", "advis",
                "mentor", "employ", "co_found", "colleague")),
    ("has", ("has", "have", "own", "possess", "contain", "include", "part_of",
             "belongs", "member_of", "consist", "comprise")),
    ("causal", ("cause", "block", "depend", "enable", "affect", "trigger", "require",
                "impact", "drive", "lead_to", "result", "prevent", "influence")),
    ("locative", ("locat", "based", "lives", "live_in", "from", "in_", "at_",
                  "headquart", "resid")),
    ("temporal", ("schedul", "before", "after", "during", "when", "due", "starts",
                  "ends", "on_", "deadline", "timeline")),
    ("is_a", ("is_a", "type_of", "instance", "kind_of", "subclass", "category_of",
              "role", "title", "position")),
]


def predicate_class(predicate: Optional[str]) -> str:
    """Bucket a predicate into one of: social, has, causal, locative, temporal,
    is_a, other — so edges can be coloured by relation kind."""
    p = (predicate or "").strip().lower().replace(" ", "_")
    if not p:
        return "other"
    for cls, keys in _PCLASS_RULES:
        for k in keys:
            if k in p:
                return cls
    return "other"


# ---- importance (PageRank) -------------------------------------------------
def pagerank(node_ids: Iterable[str], edges: Iterable[Tuple[str, str, float]],
             damping: float = 0.85, iters: int = 40) -> Dict[str, float]:
    """Weighted PageRank over an UNDIRECTED view of the graph (good enough for a
    node-importance / size signal), normalized to 0..1 by the max. O(E) per
    iteration — fine for a dashboard-sized graph."""
    ids = list(node_ids)
    n = len(ids)
    if n == 0:
        return {}
    nbrs: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    wsum: Dict[str, float] = defaultdict(float)
    for a, b, w in edges:
        w = max(float(w or 0.0), 0.01)
        nbrs[a].append((b, w)); wsum[a] += w
        nbrs[b].append((a, w)); wsum[b] += w
    pr = {x: 1.0 / n for x in ids}
    base = (1.0 - damping) / n
    for _ in range(iters):
        nxt = {x: base for x in ids}
        for x in ids:
            s = wsum.get(x, 0.0)
            if s <= 0:
                continue
            share = damping * pr[x]
            for (m, w) in nbrs[x]:
                nxt[m] += share * (w / s)
        pr = nxt
    mx = max(pr.values()) if pr else 0.0
    return {x: (pr[x] / mx if mx > 0 else 0.0) for x in ids}


# ---- adjacency helpers -----------------------------------------------------
def build_adjacency(edges: Iterable[Tuple[str, str, float]]) -> Dict[str, List[Tuple[str, float]]]:
    adj: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    for a, b, w in edges:
        w = max(float(w or 0.0), 0.01)
        adj[a].append((b, w))
        adj[b].append((a, w))
    return adj


# ---- shortest path: "how is A related to B?" -------------------------------
def shortest_path(adj: Dict[str, List[Tuple[str, float]]], a: str, b: str) -> Optional[List[str]]:
    """Confidence-weighted shortest path (Dijkstra, cost = 1/weight) between two
    nodes — returns the ordered node list, or None if disconnected."""
    if a == b:
        return [a]
    import heapq
    dist = {a: 0.0}
    prev: Dict[str, str] = {}
    pq = [(0.0, a)]
    while pq:
        d, x = heapq.heappop(pq)
        if x == b:
            break
        if d > dist.get(x, float("inf")):
            continue
        for (m, w) in adj.get(x, ()):
            nd = d + 1.0 / max(w, 0.01)
            if nd < dist.get(m, float("inf")):
                dist[m] = nd
                prev[m] = x
                heapq.heappush(pq, (nd, m))
    if b not in dist:
        return None
    path = [b]
    while path[-1] != a:
        path.append(prev[path[-1]])
    return list(reversed(path))


def ego_nodes(adj: Dict[str, List[Tuple[str, float]]], focus: str, depth: int) -> set:
    """The set of nodes within `depth` hops of `focus` (the local/ego graph)."""
    keep = {focus}
    frontier = {focus}
    for _ in range(max(0, depth)):
        nxt = set()
        for x in frontier:
            for (m, _w) in adj.get(x, ()):
                if m not in keep:
                    nxt.add(m)
        keep |= nxt
        frontier = nxt
        if not frontier:
            break
    return keep


# ---- structural bridges (articulation points) ------------------------------
def articulation_points(adj: Dict[str, List[Tuple[str, float]]]) -> set:
    """Nodes whose removal disconnects the graph — the load-bearing connectors.
    Iterative Tarjan (lowlink) so a deep graph won't blow the recursion stack."""
    nodes = list(adj.keys())
    visited: set = set()
    tin: Dict[str, int] = {}
    low: Dict[str, int] = {}
    arts: set = set()
    timer = 0
    for root in nodes:
        if root in visited:
            continue
        # iterative DFS
        stack = [(root, None, iter(adj.get(root, ())))]
        children_at: Dict[str, int] = defaultdict(int)
        visited.add(root)
        tin[root] = low[root] = timer; timer += 1
        while stack:
            node, parent, it = stack[-1]
            advanced = False
            for (to, _w) in it:
                if to == parent:
                    continue
                if to in visited:
                    low[node] = min(low[node], tin[to])
                else:
                    visited.add(to)
                    tin[to] = low[to] = timer; timer += 1
                    children_at[node] += 1
                    stack.append((to, node, iter(adj.get(to, ()))))
                    advanced = True
                    break
            if not advanced:
                stack.pop()
                if stack:
                    par = stack[-1][0]
                    low[par] = min(low[par], low[node])
                    if stack[-1][1] is not None and low[node] >= tin[par]:
                        arts.add(par)
        if children_at.get(root, 0) > 1:
            arts.add(root)
    return arts
