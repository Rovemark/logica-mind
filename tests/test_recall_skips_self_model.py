"""General recall and the user model do not return the agents' self-model records.

SelfModel (continuity/self_model.py) keeps every version of an agent's identity as a
memory in the USER layer, with importance 0.9, and never deletes one. On the appliance,
on 2026-09-27, recalling "copy de alta conversão" across namespaces returned 10 of 10
self-model versions, and in the "astro" namespace (shared by the main agent and the
user model) 8 of the 9 USER-layer hits for "o que o Andre prefere" were versions, so
ask_about_user reasoned over 1 observation instead of 8. Whoever wants the self-model
reads it with SelfModel.load, or asks for it with the `continuity` filter.
"""
from logica_mind import LogicaMind
from logica_mind.continuity import SelfModel
from logica_mind.embeddings import HashingEmbedder
from logica_mind.stores import SQLiteStore


def _mind(ns="astro"):
    return LogicaMind(store=SQLiteStore(":memory:"), embedder=HashingEmbedder(), namespace=ns)


def _is_self_model(hit):
    return (hit.memory.metadata or {}).get("continuity") == "self-model"


def test_recall_skips_self_model_versions():
    m = _mind()
    sm = SelfModel(m.store, "astro")
    for i in range(12):
        sm.save({"direction": f"copy de alta conversão, rodada {i}"})
    m.remember("A copy de alta conversão da campanha de outubro usa prova social", extract=False)
    hits = m.recall("copy de alta conversão", limit=5)
    assert hits, "the real memory disappeared from recall"
    assert not any(_is_self_model(h) for h in hits)
    assert any("prova social" in h.memory.content for h in hits)


def test_recall_across_skips_them_too():
    m = _mind()
    SelfModel(m.store, "rand").save({"direction": "SEO técnico e links"})
    m.for_namespace("rand").remember("A auditoria de SEO técnico achou 40 links quebrados", extract=False)
    hits = m.recall_across("SEO técnico", limit=5, namespaces=["rand"])
    assert hits and not any(_is_self_model(h) for h in hits)


def test_asking_by_the_filter_still_returns_them():
    m = _mind()
    SelfModel(m.store, "astro").save({"direction": "copy de alta conversão"})
    hits = m.recall("copy de alta conversão", limit=5, metadata_filter={"continuity": "self-model"})
    assert hits and all(_is_self_model(h) for h in hits)


class _PromptEcho:
    """Stands in for the LLM and hands the prompt back, so the test reads what it was fed."""
    available = True

    def complete(self, prompt, system=None, **_):
        return prompt


def test_user_model_sees_the_observations_past_the_self_model():
    m = _mind()
    sm = SelfModel(m.store, "astro")
    for i in range(20):
        sm.save({"direction": f"o que o Andre prefere: decisões rápidas, rodada {i}"})
    # the versions repeat the question's words; the observations say the same thing in
    # other words, as they do on the appliance
    facts = ["Andre toma café sem açúcar", "Reunião com Andre dura no máximo 20 minutos",
             "Andre escreve texto sem travessão"]
    for f in facts:
        m.observe_user(f)
    m.user.llm = _PromptEcho()
    prompt = m.ask_about_user("o que o Andre prefere")
    relevant = prompt.split("RELEVANT OBSERVATIONS:\n", 1)[1].split("\n\nQUESTION:", 1)[0]
    for f in facts:
        assert f in relevant
    assert "rodada" not in relevant
