"""Causal-model (simulation scaffold) tests — run with: pytest. Offline."""
from logica_mind.continuity import CausalModel


class FakeLLM:
    available = True

    def __init__(self, raise_on_json=False):
        self.raise_on_json = raise_on_json

    def complete(self, prompt, system=None):
        return ""

    def complete_json(self, prompt, system=None):
        if self.raise_on_json:
            raise RuntimeError("LLM down")
        return {"effects": [{"effect": "churn sobe", "probability": 0.7},
                            {"effect": "suporte sobrecarrega", "probability": 0.6}],
                "confidence": 0.65, "reasoning": "preço acima da elasticidade do segmento"}


class NoLLM:
    available = False
    def complete(self, prompt, system=None): return ""
    def complete_json(self, prompt, system=None): return None


class FakeMind:
    def __init__(self, llm):
        self.namespace = "astro"
        self.llm = llm
    def context(self, query, **kw):
        return "contexto causal do grafo"


def test_simulate_with_llm():
    r = CausalModel(FakeMind(FakeLLM())).simulate("subir o preço 20%")
    assert len(r["effects"]) == 2 and r["confidence"] == 0.65
    assert r["effects"][0]["effect"] == "churn sobe"
    assert "heurística" in r["caveat"].lower()        # honest scope is always stated


def test_simulate_without_llm_is_failsoft():
    r = CausalModel(FakeMind(NoLLM())).simulate("qualquer coisa")
    assert r["effects"] == [] and r["confidence"] == 0.0
    assert "indisponível" in r["reasoning"].lower()


def test_simulate_failsoft_on_llm_error():
    r = CausalModel(FakeMind(FakeLLM(raise_on_json=True))).simulate("qualquer coisa")
    assert r["effects"] == [] and r["confidence"] == 0.0     # degraded, no crash
