"""Categorization taxonomy: life dimensions + work/project/business dimensions.

Every durable fact Logica Mind extracts is tagged with two things:

  • a ``category`` — an open-vocabulary topical label the model coins ("Coffee
    preference", "Zodiac sign", "Q3 revenue target", "Launch blocker", …); the
    space of categories is effectively unbounded.
  • a ``dimension`` — one of the fixed dimensions below, each belonging to a
    GROUP. Personal dimensions are mapped to a tier of **Maslow's hierarchy of
    needs**; project / organization / business dimensions model the things an
    agent actually works on.

That turns a flat pile of facts into a structured portrait — of a person (what
they need, value and reach for) AND of the work (projects, company, finances).
"""
from __future__ import annotations

from typing import Dict, List, Optional

# Maslow's hierarchy (personal dimensions only), bottom → top.
MASLOW: List[str] = ["physiological", "safety", "belonging", "esteem", "self-actualization"]

# Top-level groups.
GROUPS: List[Dict] = [
    {"id": "personal", "label": "Personal"},
    {"id": "project", "label": "Projects"},
    {"id": "organization", "label": "Organization"},
    {"id": "business", "label": "Business & Finance"},
]

# Each dimension: id, label, group, (personal→) maslow tier, example categories.
DIMENSIONS: List[Dict] = [
    # ---- personal (mapped to Maslow) ----
    {"id": "identity", "label": "Identity", "group": "personal", "maslow": "esteem",
     "examples": ["name", "age", "gender", "nationality", "ethnicity", "languages", "zodiac sign", "personality type"]},
    {"id": "location", "label": "Location & Place", "group": "personal", "maslow": "safety",
     "examples": ["home city", "country", "current location", "hometown", "neighbourhood", "timezone"]},
    {"id": "time", "label": "Time & Schedule", "group": "personal", "maslow": "safety",
     "examples": ["daily routine", "working hours", "birthday", "anniversary", "availability", "year", "season"]},
    {"id": "preference", "label": "Preferences & Taste", "group": "personal", "maslow": "esteem",
     "examples": ["food", "drink", "music", "brand", "style", "colour", "like", "dislike"]},
    {"id": "relationship", "label": "Relationships", "group": "personal", "maslow": "belonging",
     "examples": ["family", "partner", "friend", "colleague", "pet", "community", "mentor"]},
    {"id": "health", "label": "Health & Body", "group": "personal", "maslow": "physiological",
     "examples": ["fitness", "diet", "sleep", "medical condition", "allergy", "energy", "sex"]},
    {"id": "ambition", "label": "Goals & Ambitions", "group": "personal", "maslow": "self-actualization",
     "examples": ["personal goal", "long-term dream", "aspiration", "bucket-list item", "legacy"]},
    {"id": "spirituality", "label": "Spirituality & Faith", "group": "personal", "maslow": "self-actualization",
     "examples": ["religion", "faith", "spiritual practice", "core value", "philosophy", "ritual"]},
    {"id": "emotion", "label": "Emotion & State", "group": "personal", "maslow": "belonging",
     "examples": ["mood", "feeling", "stress", "joy", "fear", "motivation"]},
    {"id": "interest", "label": "Interests & Hobbies", "group": "personal", "maslow": "self-actualization",
     "examples": ["hobby", "passion", "sport", "game", "art", "travel", "fandom"]},
    {"id": "belief", "label": "Beliefs & Opinions", "group": "personal", "maslow": "esteem",
     "examples": ["worldview", "opinion", "political view", "stance", "principle"]},
    {"id": "skill", "label": "Skills & Knowledge", "group": "personal", "maslow": "esteem",
     "examples": ["expertise", "talent", "language skill", "certification", "craft"]},
    {"id": "habit", "label": "Habits & Behaviour", "group": "personal", "maslow": "safety",
     "examples": ["routine", "ritual", "vice", "tendency", "pattern"]},
    {"id": "possession", "label": "Possessions", "group": "personal", "maslow": "safety",
     "examples": ["device", "vehicle", "property", "tool", "wardrobe"]},
    {"id": "career", "label": "Career", "group": "personal", "maslow": "esteem",
     "examples": ["job title", "employer", "profession", "career stage", "personal role"]},
    {"id": "personal_finance", "label": "Personal Finance", "group": "personal", "maslow": "safety",
     "examples": ["salary", "personal budget", "saving", "personal investment", "debt"]},
    # ---- project ----
    {"id": "project_status", "label": "Project Status", "group": "project", "maslow": None,
     "examples": ["status", "phase", "health", "progress", "completion"]},
    {"id": "project_scope", "label": "Scope & Deliverables", "group": "project", "maslow": None,
     "examples": ["scope", "requirement", "feature", "deliverable", "spec"]},
    {"id": "project_timeline", "label": "Timeline & Milestones", "group": "project", "maslow": None,
     "examples": ["milestone", "deadline", "launch date", "sprint", "schedule"]},
    {"id": "project_risk", "label": "Risks & Blockers", "group": "project", "maslow": None,
     "examples": ["risk", "blocker", "issue", "dependency", "bug"]},
    {"id": "project_team", "label": "Owners & Contributors", "group": "project", "maslow": None,
     "examples": ["owner", "contributor", "assignee", "reviewer", "responsibility"]},
    {"id": "project_decision", "label": "Decisions", "group": "project", "maslow": None,
     "examples": ["decision", "trade-off", "choice", "rationale", "approval"]},
    # ---- organization ----
    {"id": "org_team", "label": "Team & People", "group": "organization", "maslow": None,
     "examples": ["team", "hire", "headcount", "role", "org structure", "culture"]},
    {"id": "org_product", "label": "Product", "group": "organization", "maslow": None,
     "examples": ["product", "feature", "roadmap", "release", "positioning"]},
    {"id": "org_market", "label": "Market & Competition", "group": "organization", "maslow": None,
     "examples": ["market", "competitor", "segment", "trend", "differentiation"]},
    {"id": "org_strategy", "label": "Strategy & Goals", "group": "organization", "maslow": None,
     "examples": ["strategy", "OKR", "objective", "vision", "mission", "priority"]},
    {"id": "org_customer", "label": "Customers", "group": "organization", "maslow": None,
     "examples": ["customer", "account", "churn", "feedback", "support", "segment"]},
    {"id": "org_partnership", "label": "Partners & Vendors", "group": "organization", "maslow": None,
     "examples": ["partner", "vendor", "supplier", "integration", "contract"]},
    # ---- business & finance ----
    {"id": "biz_revenue", "label": "Revenue & Sales", "group": "business", "maslow": None,
     "examples": ["revenue", "MRR", "ARR", "sales", "deal", "pipeline"]},
    {"id": "biz_cost", "label": "Costs & Spend", "group": "business", "maslow": None,
     "examples": ["cost", "expense", "burn rate", "COGS", "overhead"]},
    {"id": "biz_funding", "label": "Funding & Runway", "group": "business", "maslow": None,
     "examples": ["funding", "investment", "runway", "valuation", "round", "cap table"]},
    {"id": "biz_pricing", "label": "Pricing", "group": "business", "maslow": None,
     "examples": ["price", "plan", "tier", "discount", "unit economics"]},
    {"id": "biz_metric", "label": "Metrics & KPIs", "group": "business", "maslow": None,
     "examples": ["KPI", "metric", "growth rate", "conversion", "retention", "CAC", "LTV"]},
    {"id": "biz_legal", "label": "Legal & Compliance", "group": "business", "maslow": None,
     "examples": ["contract", "policy", "compliance", "regulation", "IP", "license"]},
]

DIM_IDS: List[str] = [d["id"] for d in DIMENSIONS]
_BY_ID: Dict[str, Dict] = {d["id"]: d for d in DIMENSIONS}


def dimension(dim_id: Optional[str]) -> Optional[Dict]:
    return _BY_ID.get((dim_id or "").strip().lower())


def maslow_of(dim_id: Optional[str]) -> Optional[str]:
    d = dimension(dim_id)
    return d["maslow"] if d else None


def group_of(dim_id: Optional[str]) -> Optional[str]:
    d = dimension(dim_id)
    return d["group"] if d else None


def prompt_guidance() -> str:
    """A compact block listing every dimension by group, for the system prompt."""
    out = ["DIMENSIONS (pick the single best `dimension` id for each fact):"]
    for g in GROUPS:
        ids = [f'{d["id"]} ({d["label"]})' for d in DIMENSIONS if d["group"] == g["id"]]
        out.append(f'  {g["label"]}: ' + ", ".join(ids))
    return "\n".join(out)
