from datetime import datetime

from logica_mind.banco import notificacoes as N


class CursorFalso:
    def __init__(self):
        self.chamadas = []
        self._ultimo = None

    def execute(self, sql, params):
        self.chamadas.append((sql, params))
        if "RETURNING id,disponivel_em" in sql:
            self._ultimo = ("00000000-0000-0000-0000-000000000001", params[-1])

    def fetchone(self):
        return self._ultimo


def test_lembrete_vira_item_persistente_da_inbox():
    cur = CursorFalso()
    criados = N.sincronizar_lembretes(cur, "dono", {
        "id": "00000000-0000-0000-0000-000000000010",
        "no_id": "00000000-0000-0000-0000-000000000020",
        "titulo": "Reunião de produto",
        "props": {"quando": {"inicio": "2026-08-31", "hora": "14:00", "lembrete": "1_hora"}},
    })
    assert len(criados) == 1
    insercao = next(params for sql, params in cur.chamadas if "INSERT INTO banco.notificacao" in sql)
    assert insercao[3] == "lembrete"
    assert insercao[4] == "Reunião de produto"
    assert isinstance(insercao[-1], datetime)
    assert insercao[-1].hour == 13


def test_data_sem_lembrete_nao_polui_inbox():
    cur = CursorFalso()
    assert N.sincronizar_lembretes(cur, "dono", {
        "id": "00000000-0000-0000-0000-000000000010", "no_id": None,
        "titulo": "Sem alerta", "props": {"prazo": {"inicio": "2026-08-31"}},
    }) == []
    assert not any("INSERT INTO banco.notificacao" in sql for sql, _ in cur.chamadas)
