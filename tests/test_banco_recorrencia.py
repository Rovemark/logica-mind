from logica_mind.banco.recorrencia import proxima_data


def test_proximas_datas_calendario():
    assert proxima_data("2026-08-28", "Diária") == "2026-08-29"
    assert proxima_data("2026-08-28", "Dias úteis") == "2026-08-31"
    assert proxima_data("2026-08-28", "Semanal") == "2026-09-04"
    assert proxima_data("2026-01-31", "Mensal") == "2026-02-28"
    assert proxima_data("2024-02-29", "Anual") == "2025-02-28"


def test_regra_invalida_nao_inventa_data():
    assert proxima_data("2026-08-28", "Não repetir") is None
    assert proxima_data("data quebrada", "Diária") is None
