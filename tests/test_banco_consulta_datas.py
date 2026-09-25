from logica_mind.banco import consulta


def test_data_avancada_filtra_e_ordena_pelo_inicio():
    sql, params = consulta.montar(
        "00000000-0000-0000-0000-000000000001",
        "dono",
        {"prazo": "data"},
        filtro={"prop": "prazo", "op": "depois", "valor": "2026-08-28"},
        ordenacao=[{"prop": "prazo", "dir": "asc"}],
    )
    assert sql.count("props->%s->>'inicio'") == 2
    assert sql.count("COALESCE") == 2
    assert params.count("prazo") == 4
    assert "2026-08-28" in params


def test_datas_de_sistema_usam_coluna_real():
    sql, params = consulta.montar(
        "00000000-0000-0000-0000-000000000001",
        "dono",
        {"criado_em": "criado_em"},
        filtro={"prop": "criado_em", "op": "depois", "valor": "2026-01-01"},
    )
    assert "criado_em > %s" in sql
    assert "props->>" not in sql
    assert "2026-01-01" in params
