"""Todo operador de filtro do banco gera tantos marcadores (%s) quanto parâmetros.

Um molde que cita `{lado}` duas vezes repete no SQL o marcador da chave, mas `_lado` põe o
parâmetro dela na lista uma vez só. O Postgres recusa ("the query has 11 placeholders but 9
parameters were passed") e o filtro inteiro falha: foi o que aconteceu com `vazio` numa data em
27/09/2026, quebrando o "foco de hoje" do Deck e o "está vazio" da própria Life.
"""
import pytest

from logica_mind.banco import consulta

NO = "00000000-0000-0000-0000-000000000001"
VALOR = {
    "algum_de": ["a", "b"],
    "entre": ["2026-01-01", "2026-12-31"],
    "tem": "a",
}


def _casos():
    for op, (_molde, precisa_valor) in consulta._OPS.items():
        for tipo in ("texto", "data", "numero"):
            yield op, tipo, precisa_valor


@pytest.mark.parametrize("op,tipo,precisa_valor", list(_casos()))
def test_marcadores_batem_com_parametros(op, tipo, precisa_valor):
    filtro = {"prop": "campo", "op": op}
    if precisa_valor:
        filtro["valor"] = VALOR.get(op, "2026-09-27" if tipo == "data" else "7")
    sql, params = consulta.montar(NO, "dono", {"campo": tipo}, filtro=filtro)
    assert sql.count("%s") == len(params), f"{op} em {tipo}: {sql}"


def test_filtros_combinados_do_foco_de_hoje():
    """O filtro que o Deck mandava: foco marcado E (data do foco vazia OU começando por hoje)."""
    filtro = {"e": [
        {"prop": "foco", "op": "marcado"},
        {"ou": [{"prop": "data_do_foco", "op": "vazio"},
                {"prop": "data_do_foco", "op": "comeca_com", "valor": "2026-09-27"}]},
    ]}
    sql, params = consulta.montar(NO, "dono", {"foco": "checkbox", "data_do_foco": "data"}, filtro=filtro)
    assert sql.count("%s") == len(params)


def test_contagem_por_grupo_com_vazio():
    sql, params = consulta.montar_contagem_por_grupo(
        NO, "dono", {"estado": "selecao", "prazo": "data"}, "estado",
        filtro={"prop": "prazo", "op": "nao_vazio"},
    )
    assert sql.count("%s") == len(params)
