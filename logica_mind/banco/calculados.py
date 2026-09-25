"""Propriedades calculadas do Banco: fórmulas seguras e rollups materializados.

O resultado fica em ``linha.props``. Isso é deliberado: uma fórmula que só existe no
React não pode ser filtrada, ordenada, agregada nem usada por uma automação. A fonte de
verdade continua sendo o Mind e toda superfície observa exatamente o mesmo valor.
"""
from __future__ import annotations

import ast
import datetime as dt
import json
import math
from typing import Any


class ErroDeCalculo(ValueError):
    pass


_BINARIOS = {
    ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
}
_COMPARACOES = {
    ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
}
_NOMES = {"verdadeiro": True, "falso": False, "nulo": None,
          "True": True, "False": False, "None": None}


def _simples(valor: Any) -> Any:
    if isinstance(valor, dict):
        return valor.get("nome", valor.get("valor", valor))
    return valor


def _data(valor: Any) -> dt.date:
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    texto = str(valor or "")[:10]
    try:
        return dt.date.fromisoformat(texto)
    except ValueError as e:
        raise ErroDeCalculo(f"data inválida: {valor}") from e


def _validar_arvore(arvore: ast.AST) -> None:
    permitidos = (
        ast.Expression, ast.Constant, ast.Name, ast.BinOp, ast.UnaryOp, ast.BoolOp,
        ast.Compare, ast.IfExp, ast.Call, ast.List, ast.Tuple, ast.Load,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
        ast.UAdd, ast.USub, ast.Not, ast.And, ast.Or,
        ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    )
    nos = list(ast.walk(arvore))
    if len(nos) > 200:
        raise ErroDeCalculo("fórmula complexa demais")
    for no in nos:
        if not isinstance(no, permitidos):
            raise ErroDeCalculo(f"recurso não permitido: {type(no).__name__}")
        if isinstance(no, ast.Name) and no.id not in {
            *_NOMES, "prop", "se", "vazio", "coalesce", "concat", "soma",
            "media", "minimo", "maximo", "arredondar", "abs", "tamanho",
            "dias_entre", "hoje",
        }:
            raise ErroDeCalculo(f"nome desconhecido: {no.id}")


def validar_expressao(expressao: str) -> ast.Expression:
    texto = str(expressao or "").strip()
    if not texto:
        raise ErroDeCalculo("escreva uma fórmula")
    if len(texto) > 1000:
        raise ErroDeCalculo("fórmula deve ter no máximo 1000 caracteres")
    try:
        arvore = ast.parse(texto, mode="eval")
    except SyntaxError as e:
        raise ErroDeCalculo(f"sintaxe inválida na coluna {e.offset or 1}") from e
    _validar_arvore(arvore)
    return arvore


def avaliar_formula(expressao: str, props: dict, titulo: str = "", hoje: dt.date = None) -> Any:
    arvore = validar_expressao(expressao)
    valores = dict(props or {})
    valores.setdefault("titulo", titulo)
    hoje = hoje or dt.date.today()

    def lista(args):
        if len(args) == 1 and isinstance(args[0], (list, tuple)):
            return list(args[0])
        return list(args)

    funcoes = {
        "prop": lambda chave, padrao=None: _simples(valores.get(str(chave), padrao)),
        "se": lambda condicao, sim, nao=None: sim if condicao else nao,
        "vazio": lambda valor: valor is None or valor == "" or valor == [],
        "coalesce": lambda *args: next((v for v in args if v not in (None, "")), None),
        "concat": lambda *args: "".join("" if v is None else str(v) for v in args),
        "soma": lambda *args: sum(float(v or 0) for v in lista(args)),
        "media": lambda *args: (lambda vs: sum(vs) / len(vs) if vs else 0)([float(v) for v in lista(args) if v not in (None, "")]),
        "minimo": lambda *args: min(lista(args)), "maximo": lambda *args: max(lista(args)),
        "arredondar": lambda valor, casas=0: round(float(valor), int(casas)),
        "abs": abs, "tamanho": lambda valor: len(valor or []),
        "dias_entre": lambda inicio, fim: (_data(fim) - _data(inicio)).days,
        "hoje": lambda: hoje.isoformat(),
    }

    def executar(no):
        if isinstance(no, ast.Expression): return executar(no.body)
        if isinstance(no, ast.Constant): return no.value
        if isinstance(no, ast.Name): return _NOMES[no.id]
        if isinstance(no, (ast.List, ast.Tuple)): return [executar(x) for x in no.elts]
        if isinstance(no, ast.BinOp):
            a, b = executar(no.left), executar(no.right)
            return _BINARIOS[type(no.op)](a, b)
        if isinstance(no, ast.UnaryOp):
            v = executar(no.operand)
            return -v if isinstance(no.op, ast.USub) else +v if isinstance(no.op, ast.UAdd) else not v
        if isinstance(no, ast.BoolOp):
            valores_bool = [executar(v) for v in no.values]
            return all(valores_bool) if isinstance(no.op, ast.And) else any(valores_bool)
        if isinstance(no, ast.Compare):
            esquerda = executar(no.left)
            for operador, comparador in zip(no.ops, no.comparators):
                direita = executar(comparador)
                if not _COMPARACOES[type(operador)](esquerda, direita): return False
                esquerda = direita
            return True
        if isinstance(no, ast.IfExp): return executar(no.body if executar(no.test) else no.orelse)
        if isinstance(no, ast.Call):
            if not isinstance(no.func, ast.Name) or no.keywords:
                raise ErroDeCalculo("chamada de função inválida")
            return funcoes[no.func.id](*[executar(a) for a in no.args])
        raise ErroDeCalculo(f"expressão não suportada: {type(no).__name__}")

    try:
        resultado = executar(arvore)
        if isinstance(resultado, float) and not math.isfinite(resultado):
            raise ErroDeCalculo("resultado não é um número finito")
        json.dumps(resultado, ensure_ascii=False)
        return resultado
    except ErroDeCalculo:
        raise
    except ZeroDivisionError as e:
        raise ErroDeCalculo("divisão por zero") from e
    except Exception as e:
        raise ErroDeCalculo(str(e) or type(e).__name__) from e


def validar_config(cur, user_id: str, no_id: str, tipo: str, config: dict) -> None:
    config = config or {}
    if tipo == "formula":
        validar_expressao(config.get("expressao"))
    elif tipo == "rollup":
        relacao_id = config.get("relacao_id") or config.get("relacao_propriedade_id")
        if not relacao_id:
            raise ErroDeCalculo("escolha uma propriedade de relação")
        cur.execute("SELECT 1 FROM banco.propriedade WHERE id=%s AND no_id=%s AND user_id=%s AND tipo='relacao'",
                    (relacao_id, no_id, user_id))
        if not cur.fetchone():
            raise ErroDeCalculo("a relação escolhida não pertence a este banco")
        if not config.get("campo"):
            raise ErroDeCalculo("escolha a propriedade do banco relacionado")
        if config.get("calculo", "mostrar") not in {
            "mostrar", "contar", "unicos", "soma", "media", "minimo", "maximo",
            "percentual_marcado", "mais_recente", "mais_antigo",
        }:
            raise ErroDeCalculo("cálculo de rollup desconhecido")


def _rollup(cur, user_id: str, linha_id: str, config: dict) -> Any:
    relacao_id = config.get("relacao_id") or config.get("relacao_propriedade_id")
    campo = config.get("campo") or "titulo"
    cur.execute("SELECT l.titulo,l.props FROM banco.elo e JOIN banco.linha l ON l.id=e.destino_id AND l.user_id=e.user_id "
                "WHERE e.user_id=%s AND e.origem_id=%s AND e.propriedade_id=%s AND l.deletado_em IS NULL ORDER BY l.posicao,l.id",
                (user_id, linha_id, relacao_id))
    valores = [_simples(titulo if campo == "titulo" else (props or {}).get(campo))
               for titulo, props in cur.fetchall()]
    calculo = config.get("calculo") or "mostrar"
    preenchidos = [v for v in valores if v not in (None, "")]
    if calculo == "mostrar": return preenchidos
    if calculo == "contar": return len(valores)
    if calculo == "unicos": return len({json.dumps(v, sort_keys=True, ensure_ascii=False) for v in preenchidos})
    if calculo == "percentual_marcado": return round(100 * sum(bool(v) for v in valores) / len(valores), 2) if valores else 0
    if calculo in {"soma", "media"}:
        nums = [float(v) for v in preenchidos]
        return sum(nums) if calculo == "soma" else (sum(nums) / len(nums) if nums else 0)
    if calculo in {"minimo", "mais_antigo"}: return min(preenchidos) if preenchidos else None
    if calculo in {"maximo", "mais_recente"}: return max(preenchidos) if preenchidos else None
    return None


def recalcular_linha(cur, user_id: str, linha_id: str) -> dict | None:
    cur.execute("SELECT no_id,titulo,props FROM banco.linha WHERE id=%s AND user_id=%s AND deletado_em IS NULL",
                (linha_id, user_id))
    linha = cur.fetchone()
    if not linha: return None
    no_id, titulo, props = str(linha[0]), linha[1], dict(linha[2] or {})
    cur.execute("SELECT chave,tipo,config FROM banco.propriedade WHERE no_id=%s AND user_id=%s AND tipo IN ('formula','rollup') ORDER BY ordem",
                (no_id, user_id))
    calculadas = cur.fetchall()
    antes = json.dumps(props, sort_keys=True, ensure_ascii=False, default=str)
    formulas = [p for p in calculadas if p[1] == "formula"]
    # Fórmulas podem depender de fórmulas anteriores. Algumas passagens resolvem a
    # cadeia sem permitir recursão ilimitada.
    for _ in range(max(1, len(formulas))):
        for chave, _, config in formulas:
            try: props[chave] = avaliar_formula((config or {}).get("expressao"), props, titulo)
            except ErroDeCalculo as e: props[chave] = f"#ERRO: {str(e)[:180]}"
    for chave, _, config in (p for p in calculadas if p[1] == "rollup"):
        try: props[chave] = _rollup(cur, user_id, linha_id, config or {})
        except Exception as e: props[chave] = f"#ERRO: {str(e)[:180]}"
    depois = json.dumps(props, sort_keys=True, ensure_ascii=False, default=str)
    if depois != antes:
        cur.execute("UPDATE banco.linha SET props=%s,atualizado_em=now() WHERE id=%s AND user_id=%s RETURNING atualizado_em",
                    (json.dumps(props, ensure_ascii=False), linha_id, user_id))
        atualizado = cur.fetchone()[0].isoformat()
    else:
        atualizado = None
    return {"id": str(linha_id), "no_id": no_id, "titulo": titulo, "props": props,
            "atualizado_em": atualizado}


def recalcular_cascata(cur, user_id: str, linha_id: str, teto: int = 1000) -> dict | None:
    fila, vistos, primeiro = [str(linha_id)], set(), None
    while fila and len(vistos) < teto:
        atual = fila.pop(0)
        if atual in vistos: continue
        vistos.add(atual)
        calculada = recalcular_linha(cur, user_id, atual)
        if primeiro is None: primeiro = calculada
        cur.execute("SELECT DISTINCT origem_id FROM banco.elo WHERE user_id=%s AND destino_id=%s", (user_id, atual))
        fila.extend(str(r[0]) for r in cur.fetchall() if str(r[0]) not in vistos)
    return primeiro


def recalcular_banco(cur, user_id: str, no_id: str) -> int:
    cur.execute("SELECT id FROM banco.linha WHERE no_id=%s AND user_id=%s AND deletado_em IS NULL", (no_id, user_id))
    ids = [str(r[0]) for r in cur.fetchall()]
    for linha_id in ids: recalcular_cascata(cur, user_id, linha_id)
    return len(ids)
