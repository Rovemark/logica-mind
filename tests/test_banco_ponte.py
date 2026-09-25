from logica_mind import LogicaMind
from logica_mind.banco import ponte
from logica_mind.stores.memory import InMemoryStore
import time


class _Cursor:
    def __init__(self, eventos):
        self.eventos = eventos
        self.processados = []
        self.erros = []
        self._resultado = []

    def execute(self, sql, params=None):
        if "SELECT id,user_id,tipo,payload" in sql:
            self._resultado = list(self.eventos)
        elif "SET processado_em=now()" in sql:
            self.processados.append(params[0])
        elif "SET tentativas=tentativas+1" in sql:
            self.erros.append(params)
        return self

    def fetchall(self):
        return self._resultado

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _Pool:
    def __init__(self, eventos):
        self.cursor_atual = _Cursor(eventos)

    def connection(self):
        return _Connection(self.cursor_atual)


def _evento(ident, tipo, payload):
    return (ident, "alice", tipo, payload)


def test_snapshot_substitui_estado_e_remocao_esquece():
    mind = LogicaMind(namespace="ceo", store=InMemoryStore())
    primeiro = {
        "recurso": "linha:42", "recurso_tipo": "linha", "recurso_id": "42",
        "linha_id": "42", "no_id": "7", "titulo": "Plano Alfa",
        "modelo": "projetos", "texto": "Projeto Plano Alfa. Estado: planejamento.",
    }
    pool = _Pool([_evento(1, "vida_snapshot", primeiro)])
    assert ponte.drenar(mind, pool, ceder_se_leitura_ha=0) == 1
    memorias = mind.store.all(ponte.NAMESPACE)
    assert len(memorias) == 1
    assert memorias[0].metadata["ownerId"] == "alice"
    assert memorias[0].metadata["source"] == "logica-life"
    assert memorias[0].metadata["life_scope"] == "owner"
    assert "planejamento" in memorias[0].content

    segundo = {**primeiro, "texto": "Projeto Plano Alfa. Estado: concluído."}
    pool = _Pool([_evento(2, "vida_snapshot", segundo)])
    assert ponte.drenar(mind, pool, ceder_se_leitura_ha=0) == 1
    memorias = mind.store.all(ponte.NAMESPACE)
    assert len(memorias) == 1
    assert "concluído" in memorias[0].content
    assert "planejamento" not in memorias[0].content

    pool = _Pool([_evento(3, "vida_remover", {
        "recurso": "linha:42", "linha_id": "42", "no_id": "7",
    })])
    assert ponte.drenar(mind, pool, ceder_se_leitura_ha=0) == 1
    assert mind.store.all(ponte.NAMESPACE) == []


def test_fragmentos_sao_limitados_e_preservam_o_texto_curto(monkeypatch):
    monkeypatch.setattr(ponte, "_TAMANHO_FRAGMENTO", 400)
    monkeypatch.setattr(ponte, "_MAX_FRAGMENTOS", 8)
    curto = "Página do Life.\nUma decisão importante."
    assert ponte._fragmentos(curto) == [curto]
    grandes = ponte._fragmentos("x" * 10_000)
    assert len(grandes) == 8
    assert all(len(parte) <= 400 for parte in grandes)


def test_metadados_de_progresso_tambem_sao_isolados_por_owner():
    md = ponte.metadados("projeto_concluido", "alice", {"no_id": "7"})
    assert md["ownerId"] == "alice"
    assert md["origem"] == "banco"


def test_polling_continuo_nao_deixa_a_ponte_com_fome():
    mind = LogicaMind(namespace="ceo", store=InMemoryStore())
    pool = _Pool([_evento(9, "vida_snapshot", {
        "recurso": "no:9", "no_id": "9", "titulo": "Página viva",
        "texto": "Uma decisão que precisa chegar à memória.",
    })])
    mind.store._last_read_at = time.monotonic()
    assert ponte.drenar(mind, pool, ceder_se_leitura_ha=2, maximo_adiamento=5) == 0
    mind._vida_ponte_ultimo_dreno = time.monotonic() - 6
    mind.store._last_read_at = time.monotonic()
    assert ponte.drenar(mind, pool, ceder_se_leitura_ha=2, maximo_adiamento=5) == 1
    assert any("decisão" in m.content for m in mind.store.all(ponte.NAMESPACE))
