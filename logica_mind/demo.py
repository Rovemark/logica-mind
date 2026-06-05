"""Optional demo dataset — a rich, fully fictional world so a fresh dashboard
looks populated and every feature is visible (calendar heatmap, knowledge graph,
communities, user model, peers, contradictions, session records, insights).

It is 100% made up (a fictional company, "Acme Inc"); nothing here is real data.
Seed it, explore, then clear it with one call — the seeded rows are tagged so the
cleanup is surgical and never touches anything you added yourself.

    from logica_mind import LogicaMind
    from logica_mind import demo
    mind = LogicaMind()
    demo.seed(mind)        # populate
    demo.clear(mind)       # remove every demo row, leave your own data intact

From the CLI:  ``logica-mind demo``  (seed)  ·  ``logica-mind demo --clear``
From the dashboard: a banner offers "Clear demo" / "Keep" on first launch.

Offline by design: uses whatever embedder the mind has (the default hashing
embedder needs no API key), so the demo works with zero configuration.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from .types import Memory, MemoryLayer

if TYPE_CHECKING:
    from .core import LogicaMind

# every row the demo writes carries this flag in metadata, so clear() can remove
# exactly the demo and nothing the user created.
DEMO_FLAG = "demo"

# a fictional org: role-based agents, a founder, and neutral projects.
AGENTS = ["research", "marketing", "engineering", "finance", "product", "support"]
FOUNDER = "Maya Chen"
COMPANY = "Acme Inc"
PROJECTS = ["the mobile app", "the billing service", "the docs site",
            "the data pipeline", "the analytics dashboard", "the onboarding flow"]
TOPICS = ["pricing", "retention", "the launch", "onboarding", "latency",
          "the roadmap", "churn", "the funnel", "accessibility", "the redesign"]


def _metric(rng: random.Random) -> str:
    return rng.choice([
        f"{rng.randint(2, 40)} tickets open", f"{rng.randint(100, 5200)} signups",
        f"${rng.randint(1, 90)}k MRR", f"{rng.randint(80, 99)}% uptime",
        f"{rng.randint(5, 95)}% done", f"a {rng.randint(2, 9)}x lift",
    ])


# templated semantic facts per agent — varied so recall/graph/insights look real
_SEM = {
    "research": ["User interviews on {t} show a clear pattern for {p}.",
                 "Synthesized {p} findings: {m}.", "{p} hypothesis on {t} validated.",
                 "Competitive scan for {p} done — {t} is the gap."],
    "marketing": ["Campaign for {p} leads with the {t} promise.",
                  "Organic on {p}: {m}.", "New angle for {p}: {t} as the headline.",
                  "{p} positioning centers on {t}."],
    "engineering": ["Shipped {p} — {m}.", "Fixed a flaky test in {p}; root cause was a race.",
                    "{p} now has a retry guard around {t}.", "Refactored {t} in {p} for {m}."],
    "finance": ["{p} stays cash-neutral until {t} lands.", "Modeled {t} for {p}: {m}.",
                "Runway covers {p} through next quarter.", "{p} unit economics improved to {m}."],
    "product": ["Prioritized {t} for {p} this sprint.", "{p} roadmap: {t} before the launch.",
                "Cut scope on {p} — {t} ships first.", "{p} sitting at {m}."],
    "support": ["Most {p} tickets are about {t}.", "Wrote a help doc for {t} on {p}.",
                "{p} CSAT up after the {t} fix.", "Escalated a {t} issue on {p}: {m}."],
}
_EPISODIC = ["how's {p} looking?", "any blockers on {t}?", "ship {p} this week?",
             "what changed on {p}?", "status on {t}?", "is {p} ready?"]


def _seed_at(base: datetime, rng: random.Random, days_ago: int) -> str:
    d = base - timedelta(days=days_ago, hours=rng.randint(0, 11), minutes=rng.randint(0, 59))
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def seed(mind: "LogicaMind", *, rng_seed: int = 7, days: int = 75) -> int:
    """Populate `mind` with a rich fictional demo spanning ~`days` days. Returns
    the number of memories written. Every row is tagged so clear() can undo it."""
    rng = random.Random(rng_seed)
    base = datetime.now(timezone.utc)
    written = 0

    def _flag(m: Memory) -> Memory:
        md = dict(m.metadata or {}); md[DEMO_FLAG] = True
        m.metadata = md
        if DEMO_FLAG not in (m.tags or []):
            m.tags = (m.tags or []) + [DEMO_FLAG]
        return m

    def add(ns: str, content: str, layer: MemoryLayer, days_ago: int,
            importance: float = 0.5, tags=None, meta=None) -> None:
        nonlocal written
        sub = mind.for_namespace(ns)
        sub.store.add([_flag(Memory(
            content=content, namespace=ns, layer=layer, importance=importance,
            embedding=sub._embed(content), created_at=_seed_at(base, rng, days_ago),
            tags=list(tags or []), metadata=dict(meta or {}),
        ))])
        written += 1

    # ---- semantic + episodic, spread across agents and time ----
    for ns in AGENTS:
        for _ in range(14):
            content = rng.choice(_SEM[ns]).format(
                p=rng.choice(PROJECTS), t=rng.choice(TOPICS), m=_metric(rng))
            add(ns, content, MemoryLayer.SEMANTIC, rng.randint(0, days),
                importance=round(rng.uniform(0.4, 0.9), 2),
                meta={"source": rng.choice(["claude-code", "cursor", "chatgpt"])})
        for _ in range(8):
            q = rng.choice(_EPISODIC).format(p=rng.choice(PROJECTS), t=rng.choice(TOPICS))
            add(ns, q, MemoryLayer.EPISODIC, rng.randint(0, days),
                importance=0.3, meta={"role": "user", "session": f"demo-{ns}-{rng.randint(1, 3)}"})

    # ---- knowledge graph: founder, company, reporting, ownership ----
    # shared entities (Maya, Acme Inc, projects) appear across agents → gold nodes.
    # graph.ingest() stores the edge as a GRAPH memory tagged "edge"; we re-fetch
    # the matching row and flag it so clear() can remove it (ingest takes no metadata).
    def edge(s, p, o, ns="research"):
        nonlocal written
        sub = mind.for_namespace(ns)
        e = sub.graph.ingest(s, p, o)
        for m in sub.store.all(ns, [MemoryLayer.GRAPH]):
            md = m.metadata or {}
            if (str(md.get("subject", "")).lower() == e.subject.lower()
                    and str(md.get("object", "")).lower() == e.object.lower()
                    and str(md.get("predicate", "")).lower() == p.lower()):
                sub.store.add([_flag(m)])
        written += 1

    edge(FOUNDER, "founded", COMPANY)
    for ns in AGENTS:
        edge(ns, "reports_to", FOUNDER, ns=ns)
        edge(ns, "part_of", COMPANY, ns=ns)
    edge("engineering", "owns", "the billing service", ns="engineering")
    edge("product", "owns", "the mobile app", ns="product")
    edge("marketing", "owns", "the docs site", ns="marketing")
    edge("research", "studies", "user retention")
    # a contradiction over time (the time-machine / changelog feature)
    edge("the launch", "scheduled_for", "March 15", ns="engineering")
    edge("the launch", "scheduled_for", "May 1", ns="engineering")

    # ---- peers: directional observations ----
    for obr, obd in [("product", "engineering"), ("marketing", "research"),
                     ("finance", "product")]:
        m = mind.for_namespace(obr).observe_peer(
            obr, obd, f"{obd} prefers concrete specs before committing.")
        if m:
            mind.store.add([_flag(m)]); written += 1

    # ---- dialectic user model ----
    for txt in ["Prefers concise, structured answers.",
                "Works across product and engineering.",
                "Cares about latency and accessibility.",
                "Reviews the roadmap every Monday."]:
        m = mind.for_namespace("product").observe_user(txt)
        if m:
            mind.store.add([_flag(m)]); written += 1

    # ---- structured session/run records (the multi-agent run feature) ----
    rec = mind.for_namespace("product").record_session(
        title="Ship the onboarding redesign",
        participants=[
            {"name": "research", "role": "discovery", "contribution": "Mapped the drop-off points.", "metrics": {"score": 92}},
            {"name": "product", "role": "spec", "contribution": "Wrote the redesign spec.", "metrics": {"score": 96}},
            {"name": "engineering", "role": "build", "contribution": "Implemented the new flow."},
            {"name": "marketing", "role": "launch", "contribution": "Drafted the announcement."},
        ],
        status="completed",
        metrics={"tokens": 18420, "cost_usd": 0.14, "score": 94},
        links={"sprint": "2026-Q2-S3"},
    )
    mind.store.add([_flag(rec)]); written += 1
    for m in mind.store.all("product", [MemoryLayer.EPISODIC]):
        if "contribution" in (m.tags or []) and (m.metadata or {}).get("session") == rec.metadata.get("session"):
            mind.store.add([_flag(m)])

    # ---- a connected org graph (ORG-typed namespace) ----
    # one densely-linked namespace so Observations has real structure to find:
    # the founder/company become hub nodes, and people who report to the same
    # founder + belong to the same company show up as recurring co-occurrences.
    people = ["Alex Rivera", "Sam Okafor", "Jordan Lee", "Priya Nair"]
    edge(FOUNDER, "founded", COMPANY, ns="org:acme")
    for person in people:
        edge(person, "reports_to", FOUNDER, ns="org:acme")
        edge(person, "works_at", COMPANY, ns="org:acme")
    edge("Alex Rivera", "owns", "the mobile app", ns="org:acme")
    edge("Sam Okafor", "owns", "the billing service", ns="org:acme")
    edge("Jordan Lee", "leads", "the data pipeline", ns="org:acme")
    edge("the mobile app", "part_of", COMPANY, ns="org:acme")
    edge("the billing service", "part_of", COMPANY, ns="org:acme")

    # ---- categorized facts on the org entities ----
    # lights up the new graph layers + the Profile in the demo: facts carry a
    # life/work dimension (life-areas + categorization), pairs that get talked
    # about together WITHOUT an edge become co-mentions, and 'Maya'/'Acme' fold
    # onto their canonical nodes via aliases.
    ORG_FACTS = [
        ("Acme Inc hit $45k MRR in Q3, up 30% quarter over quarter.", "biz_revenue", "MRR"),
        ("Acme Inc closed a $2M seed round at a $12M valuation.", "biz_funding", "Fundraising"),
        ("Acme Inc set the new pricing tier at $49/mo.", "biz_pricing", "Pricing"),
        ("Priya Nair leads research on user retention at Acme Inc.", "org_strategy", "Strategy"),
        ("Alex Rivera maintains the data pipeline behind the analytics.", "org_product", "Platform"),
        ("The mobile app launch slipped to May, blocked on a payments bug.", "project_timeline", "Launch"),
        # co-mention pairs (no direct edge) — each said twice so they cross cooc_min
        ("Sam Okafor and Priya Nair shipped the analytics dashboard.", "org_product", "Platform"),
        ("Sam Okafor and Priya Nair paired on the retention metrics.", "org_strategy", "Metrics"),
        ("Alex Rivera and Jordan Lee debated the data pipeline design.", "project_decision", "Architecture"),
        ("Alex Rivera and Jordan Lee reviewed the pipeline rollout.", "project_status", "Status"),
        # the founder as a person — personal life-areas up Maslow
        ("Maya Chen is a Scorpio who meditates every morning before work.", "spirituality", "Daily ritual"),
        ("Maya Chen dreams of building a company that outlives her.", "ambition", "Legacy"),
        ("Maya Chen prefers strong flat whites and works from cafés on Fridays.", "preference", "Coffee preference"),
    ]
    for content, dim, cat in ORG_FACTS:
        add("org:acme", content, MemoryLayer.SEMANTIC, rng.randint(0, days),
            importance=0.7, meta={"dimension": dim, "category": cat, "source": "claude-code"})
    org = mind.for_namespace("org:acme")
    org.add_alias("Maya", FOUNDER)
    org.add_alias("Acme", COMPANY)
    for am in org.store.all("org:acme", [MemoryLayer.GRAPH]):
        if "alias" in (am.tags or []):
            org.store.add([_flag(am)])

    # ---- a USER-typed context (the founder's own memory) ----
    # gives the Memory Lake a typed catalog (USER / ORG / AGENT) instead of one
    # uniform kind, and a richer User view for this namespace.
    for txt in ["Maya prefers async updates over standups.",
                "Maya's north-star metric is weekly active teams.",
                "Maya reviews the roadmap every Monday morning.",
                "Maya is based in Lisbon (GMT)."]:
        add("user:maya", txt, MemoryLayer.SEMANTIC, rng.randint(0, days),
            importance=0.7, meta={"source": "claude-code"})
    mu = mind.for_namespace("user:maya").observe_user("Decides fast once the data is in front of her.")
    if mu:
        mind.store.add([_flag(mu)]); written += 1

    return written


def count(mind: "LogicaMind") -> int:
    """How many demo-tagged memories exist across all namespaces."""
    n = 0
    for ns in mind.store.namespaces():
        for m in mind.store.all(ns):
            if (m.metadata or {}).get(DEMO_FLAG) or DEMO_FLAG in (m.tags or []):
                n += 1
    return n


def clear(mind: "LogicaMind") -> int:
    """Remove every demo-tagged memory across all namespaces, leaving anything the
    user added untouched. Returns the number deleted."""
    deleted = 0
    for ns in mind.store.namespaces():
        for m in list(mind.store.all(ns)):
            if (m.metadata or {}).get(DEMO_FLAG) or DEMO_FLAG in (m.tags or []):
                if mind.store.delete(ns, m.id):
                    deleted += 1
    return deleted
