"""Heartbeat tests — run with: pytest. Offline (InMemoryStore + fakes).

Covers the cycle's guarantees: it pulses with no LLM (fail-soft), it generates
falsifiable hypotheses and folds high-confidence ones into the self-model, it
self-corrects due hypotheses and surfaces refutations to a notifier, and a flaky
LLM never breaks the beat.
"""
from logica_mind.stores import InMemoryStore
from logica_mind.types import SearchResult
from logica_mind.continuity import Heartbeat, SelfModel


class NoLLM:
    available = False
    def complete(self, prompt, system=None): return ""
    def complete_json(self, prompt, system=None): return None


class FakeLLM:
    available = True
    name = "fake"

    def __init__(self, hyps=None, verdict="confirmed", raise_on_json=False):
        # `verificacao` é OBRIGATÓRIO desde o conserto do acervo travado: hipótese sem
        # critério observável é descartada na entrada (ver test_hipotese_sem_criterio_*).
        self.hyps = hyps if hyps is not None else [
            {"text": "usuário quer foto real", "verificacao": "próximo criativo aprovado usa foto",
             "confidence": 0.9},
            {"text": "funil precisa de antes/depois", "verificacao": "CTR do passo 2 sobe 10%",
             "confidence": 0.6},
        ]
        self.verdict = verdict
        self.raise_on_json = raise_on_json

    def complete(self, prompt, system=None): return ""

    def complete_json(self, prompt, system=None):
        if self.raise_on_json:
            raise RuntimeError("LLM down")
        if "verdict" in prompt:                       # the judge prompt
            return {"verdict": self.verdict, "why": "evidência X", "confidence": 0.8}
        if "HIPÓTESES FALSIFICÁVEIS" in prompt:        # the hypothesize prompt
            return self.hyps
        return None


class FakeMind:
    """Minimal stand-in for LogicaMind: just what Heartbeat drives."""

    def __init__(self, store, namespace, llm):
        self.store = store
        self.namespace = namespace
        self.llm = llm
        self.embedder = None
        self.dreamed = False

    def recall(self, query, limit=8, **kw):
        return [SearchResult(memory=m, score=1.0) for m in self.store.all(self.namespace)[:limit]]

    def dream(self, **kw):
        self.dreamed = True

    def context(self, query, **kw):
        return "contexto de teste"


def mk(llm, ns="astro"):
    return FakeMind(InMemoryStore(), ns, llm)


def test_beat_pulses_without_llm():
    mind = mk(NoLLM())
    rep = Heartbeat(mind).beat()
    assert rep["llm"] is False
    assert rep["hypotheses"] == 0 and rep["corrected"] == 0
    assert rep["steps"]["consolidate"] == "ok" and mind.dreamed     # the beat still ran
    assert "ms" in rep                                              # no exception, full report


def test_beat_generates_hypotheses_and_writes_selfmodel():
    mind = mk(FakeLLM())
    # large check window → created hypotheses are NOT due in this same beat
    rep = Heartbeat(mind, check_after_seconds=3600).beat()
    assert rep["hypotheses"] == 2 and rep["corrected"] == 0
    sm = SelfModel(mind.store, "astro").load()
    texts = [b["text"] for b in sm["beliefs"]]
    assert any("foto real" in t for t in texts)                    # the 0.9 hyp became a belief
    assert not any("antes/depois" in t for t in texts)             # the 0.6 hyp did NOT (below 0.7)


def test_self_correct_resolves_and_surfaces():
    notes = []
    mind = mk(FakeLLM(verdict="refuted"))
    # check_after=0 → the hypotheses created this beat are immediately due
    rep = Heartbeat(mind, check_after_seconds=0, notifier=notes.append).beat()
    assert rep["hypotheses"] == 2
    assert rep["corrected"] == 2 and rep["surfaced"] == 2
    assert len(notes) == 1 and "refutada" in notes[0]
    sm = SelfModel(mind.store, "astro").load()
    assert any("auto-corrigiu" in w for w in sm["recent"]["wins"])  # the lesson was folded in


def test_fail_soft_on_llm_error():
    mind = mk(FakeLLM(raise_on_json=True))
    rep = Heartbeat(mind).beat()                                    # must not raise
    assert rep["llm"] is True and rep["hypotheses"] == 0            # degraded, but pulsed
    assert rep["steps"]["consolidate"] == "ok"


def test_beat_publishes_confirmed_to_shared_cortex():
    from logica_mind.continuity import WorldInsights
    store = InMemoryStore()
    mind = FakeMind(store, "dev", FakeLLM(verdict="confirmed"))
    Heartbeat(mind, check_after_seconds=0).beat()                   # dev confirms its hypotheses
    top = WorldInsights(store).top_for("luna")                      # luna wakes up knowing
    assert len(top) >= 1 and all(m.metadata["agent"] == "dev" for m in top)


def test_scoped_beat_keeps_every_written_memory_in_company_owner():
    store = InMemoryStore()
    mind = FakeMind(store, "dev", FakeLLM(verdict="confirmed"))
    scope = {"ownerId": "empresa-acme", "project": "projects/site"}
    rep = Heartbeat(mind, check_after_seconds=0, metadata_scope=scope).beat()
    assert rep["steps"]["consolidate"] == "skip(scoped)"
    written = store.all("dev") + store.all("__world__")
    assert written
    assert all(all((m.metadata or {}).get(k) == v for k, v in scope.items()) for m in written)


# ─────────────────────────────────────────────────────────────────────────────
# O ACERVO QUE TRAVOU — 16.304 hipóteses, 85% abertas, 97% já vencidas, a mais
# antiga parada havia 5 semanas. Três defeitos somados; um teste para cada.
# ─────────────────────────────────────────────────────────────────────────────

def _hyp(store, ns, texto, check_after, status="open", tentativas=0):
    """Injeta uma hipótese com vencimento controlado, como se viesse de batidas passadas."""
    from logica_mind.types import Memory, MemoryLayer
    import uuid as _u
    m = Memory(
        content=texto, namespace=ns, layer=MemoryLayer.SEMANTIC,
        id=f"hyp::{ns}::{_u.uuid4().hex[:8]}", importance=0.5,
        metadata={"continuity": "heartbeat", "kind": "hypothesis", "status": status,
                  "confidence": 0.5, "created_at": "2026-06-23T15:00:00Z",
                  "judge_attempts": tentativas, "check_after": check_after},
    )
    store.add([m])
    return m


def test_fila_ordena_por_vencimento_nao_por_insercao():
    """DEFEITO 1: store.all() devolve em ordem de INSERÇÃO e o [:max_corrections]
    pegava sempre as mesmas primeiras — as de trás nunca eram olhadas."""
    mind = mk(NoLLM())
    # inserida PRIMEIRO, mas vence por ÚLTIMO
    _hyp(mind.store, "astro", "recente", "2026-07-01T00:00:00Z")
    _hyp(mind.store, "astro", "antiga", "2026-06-01T00:00:00Z")
    fila = Heartbeat(mind)._open_due_hypotheses()
    assert [m.content for m in fila] == ["antiga", "recente"], \
        "a fila tem de sair por vencimento; em ordem de inserção a antiga nunca chega a ser julgada"


def test_open_repetido_faz_backoff_e_depois_aposenta():
    """DEFEITO 2: veredito 'open' deixava a hipótese intacta — mesmo check_after já
    vencido → voltava ao topo na batida seguinte e era rejulgada para sempre."""
    mind = mk(FakeLLM(verdict="open"))
    hb = Heartbeat(mind, check_after_seconds=3600, max_judge_attempts=3)
    m = _hyp(mind.store, "astro", "irrespondível", "2020-01-01T00:00:00Z")

    hb._self_correct("ctx", "obs")                       # 1ª: backoff, sai da frente
    meta = mind.store.all("astro")[0].metadata
    assert meta["judge_attempts"] == 1 and meta["status"] == "open"
    assert meta["check_after"] > "2026", "sem empurrar o vencimento ela reaparece no topo já já"
    assert hb._open_due_hypotheses() == [], "com backoff ela NÃO pode estar vencida agora"

    for _ in range(2):                                   # força as tentativas restantes
        mm = mind.store.all("astro")[0]
        mm.metadata = {**mm.metadata, "check_after": "2020-01-01T00:00:00Z"}
        mind.store.add([mm])
        hb._self_correct("ctx", "obs")

    meta = mind.store.all("astro")[0].metadata
    assert meta["status"] == "unfalsifiable", "3 vereditos 'open' = não é falsificável, aposenta"
    assert hb._open_due_hypotheses() == [], "aposentada não pode mais consumir vaga de correção"


def test_retire_stale_drena_backlog_sem_gastar_llm():
    """DEFEITO 3: backlog herdado só sairia da frente após semanas de julgamento PAGO.
    Vencida há tempo demais é aposentada por comparação de data, custo zero."""
    mind = mk(NoLLM())                                   # sem LLM: prova que não há chamada
    _hyp(mind.store, "astro", "podre", "2020-01-01T00:00:00Z")
    _hyp(mind.store, "astro", "fresca", "2099-01-01T00:00:00Z")
    hb = Heartbeat(mind, stale_after_seconds=7 * 24 * 3600)
    assert hb._retire_stale() == 1
    por_texto = {m.content: (m.metadata or {}).get("status") for m in mind.store.all("astro")}
    assert por_texto["podre"] == "unfalsifiable"
    assert por_texto["fresca"] == "open", "só a vencida há muito tempo é aposentada"


def test_hipotese_sem_criterio_de_verificacao_e_descartada():
    """A raiz de 85% travado: especulação psicológica não tem observação que a feche,
    então o juiz responde 'open' para sempre. Sem `verificacao`, não entra."""
    mind = mk(FakeLLM(hyps=[
        {"text": "André está em modo de validação crítica", "confidence": 0.9},   # sem critério
        {"text": "o CAC do canal X cai abaixo de R$300",
         "verificacao": "relatório de CAC do mês seguinte", "confidence": 0.8},
    ]))
    rep = Heartbeat(mind, check_after_seconds=3600).beat()
    assert rep["hypotheses"] == 1, "a psicológica tem de ser recusada na entrada"
    guardadas = [m.content for m in mind.store.all("astro")
                 if (m.metadata or {}).get("kind") == "hypothesis"]
    assert guardadas == ["o CAC do canal X cai abaixo de R$300"]
