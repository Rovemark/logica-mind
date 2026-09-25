import datetime as dt

import pytest

from logica_mind.banco.calculados import ErroDeCalculo, avaliar_formula, validar_expressao


def test_formula_calcula_campos_condicao_e_funcoes_em_portugues():
    props = {"quantidade": 3, "preco": 12.5, "estado": "Pronto", "tags": ["A", "B"]}
    assert avaliar_formula('prop("quantidade") * prop("preco")', props) == 37.5
    assert avaliar_formula('se(prop("estado") == "Pronto", "Pode iniciar", "Aguardar")', props) == "Pode iniciar"
    assert avaliar_formula('concat(prop("estado"), " · ", tamanho(prop("tags")))', props) == "Pronto · 2"
    assert avaliar_formula('dias_entre("2026-08-01", "2026-08-28")', props) == 27
    assert avaliar_formula('hoje()', props, hoje=dt.date(2026, 8, 28)) == "2026-08-28"


def test_formula_falha_legivel_sem_executar_python_arbitrario():
    with pytest.raises(ErroDeCalculo, match="recurso não permitido"):
        validar_expressao('__import__("os").system("echo nunca")')
    with pytest.raises(ErroDeCalculo, match="nome desconhecido"):
        validar_expressao('segredo + 1')
    with pytest.raises(ErroDeCalculo, match="divisão por zero"):
        avaliar_formula('10 / 0', {})
