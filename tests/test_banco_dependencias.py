from datetime import date

from logica_mind.banco import dependencias as D


def test_intervalo_inteiro_se_move_sem_perder_metadados():
    valor = {"inicio": "2026-08-28", "fim": "2026-08-30", "hora": "09:30", "lembrete": "1_hora"}
    limites = {"chave": "quando", "valor": valor, "inicio": date(2026, 8, 28),
               "fim": date(2026, 8, 30), "fim_separado": None}
    novos = D._mover_props({"quando": valor, "nota": "preservada"}, limites, date(2026, 9, 2))
    assert novos["quando"] == {"inicio": "2026-09-02", "fim": "2026-09-04",
                                "hora": "09:30", "lembrete": "1_hora"}
    assert novos["nota"] == "preservada"


def test_inicio_e_fim_em_campos_separados_andam_juntos():
    props = {"inicio": "2026-08-28", "fim": "2026-09-01"}
    limites = D._limites(props, [("inicio", "Início"), ("fim", "Fim")])
    novos = D._mover_props(props, limites, date(2026, 9, 3))
    assert novos == {"inicio": "2026-09-03", "fim": "2026-09-07"}


def test_datas_com_horario_preservam_sufixo():
    assert D._iso_com_mesmo_sufixo("2026-08-28T14:20:00-03:00", date(2026, 9, 1)) == \
           "2026-09-01T14:20:00-03:00"
