"""Motor de consulta do Banco de dados: filtro em árvore, ordenação, agrupamento, cursor.

DECISÃO IRREVERSÍVEL DO PROJETO: filtrar no SERVIDOR, sempre. Filtrar no cliente
funciona lindamente com 200 linhas e mata o produto em 5 mil, e o conserto depois não
é "acrescentar paginação": é reescrever as cinco vistas, a barra, o cache e o
agrupamento, porque todos assumem o array inteiro em memória.

O filtro é ÁRVORE desde o primeiro dia, não lista plana:

    {"e":  [ {...}, {"ou": [ {...}, {...} ]} ]}
    {"prop": "status", "op": "igual", "valor": "aberto"}

Nascer plano e virar árvore depois é caro porque o formato já está gravado nas vistas
salvas do usuário. Grupo aninhado é a diferença entre "prazo hoje E (prioridade alta
OU marcado como foco)" e não conseguir perguntar isso.

Sobre o índice GIN em `props`: ele serve `@>` (par chave/valor exato). NÃO serve faixa
nem ordenação. Um calendário filtrando por mês, ou um quadro ordenado por prioridade,
faria varredura da base inteira e ninguém entenderia por quê. Por isso existe
`garantir_indice`: índice btree de expressão criado sob demanda quando o usuário salva
uma vista que filtra ou ordena por aquela propriedade, com teto por base.
"""
from __future__ import annotations

import json
import re
import base64
import binascii
import hashlib
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

_CHAVE_OK = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

# op -> (molde SQL, precisa de valor)
_OPS = {
    "igual":        ("{lado} = {v}", True),
    "diferente":    ("({lado} IS DISTINCT FROM {v})", True),
    "contem":       ("{lado} ILIKE {v_like}", True),
    # {lado} uma vez só por molde: `_lado` põe o parâmetro da chave na lista UMA vez, e o
    # marcador repetido no texto pedia o parâmetro de novo ("the query has 11 placeholders but
    # 9 parameters", medido em 27/09/2026 com `vazio` numa data). As formas abaixo dizem o
    # mesmo que "lado IS NULL OR ..." citando o lado uma vez.
    "nao_contem":   ("COALESCE({lado} NOT ILIKE {v_like}, TRUE)", True),
    "comeca_com":   ("{lado} ILIKE {v_prefixo}", True),
    "vazio":        ("NULLIF({lado}, '') IS NULL", False),
    "nao_vazio":    ("NULLIF({lado}, '') IS NOT NULL", False),
    "maior":        ("{lado_num} > {v_num}", True),
    "maior_igual":  ("{lado_num} >= {v_num}", True),
    "menor":        ("{lado_num} < {v_num}", True),
    "menor_igual":  ("{lado_num} <= {v_num}", True),
    "antes":        ("{lado_data} < {v_data}", True),
    "depois":       ("{lado_data} > {v_data}", True),
    "entre":        ("{lado_data} BETWEEN {v_data} AND {v_data2}", True),
    "algum_de":     ("{lado} = ANY({v_lista})", True),
    "marcado":      ("(props->%(K)s)::boolean IS TRUE", False),
    "desmarcado":   ("(props->%(K)s)::boolean IS NOT TRUE", False),
    "tem":          ("props @> {v_json}", True),      # multi-seleção contém item
}

# Tipos cujo valor é comparado como NÚMERO, não como texto. Sem isto, "10" < "9"
# seria verdadeiro (ordem lexicográfica) e o filtro devolveria coisa errada sem dar erro.
_NUMERICOS = {"numero", "moeda", "rollup"}

# DATA COMPARA COMO TEXTO, de propósito, e isto é decisão, não descuido.
# `texto::timestamptz` é STABLE, não IMMUTABLE (depende de DateStyle e TimeZone da
# sessão), e o Postgres RECUSA função estável em expressão de índice. Com o cast, o
# filtro de prazo funcionaria mas nunca teria índice: um calendário filtrando por mês
# varreria a base inteira.
# Data em ISO-8601 ordena lexicograficamente igual a cronologicamente
# ("2026-08-09" < "2026-08-26"), então comparar como texto é correto E indexável.
# O preço: a gravação PRECISA normalizar para ISO. "2026-8-5" quebraria a ordem, e é
# por isso que a coerção do tipo `data` normaliza antes de gravar.
_DATAS = {"data", "criado_em", "atualizado_em"}


class ErroDeConsulta(ValueError):
    pass


class ErroDeCursorExpirado(ErroDeConsulta):
    codigo = 409


def _valida_chave(chave: str) -> str:
    if not isinstance(chave, str) or not _CHAVE_OK.fullmatch(chave):
        raise ErroDeConsulta(f"chave de propriedade inválida: {chave!r}")
    return chave


class _Montador:
    """Monta SQL parametrizado. A chave da propriedade é validada contra o mesmo
    formato do CHECK da tabela ANTES de encostar na consulta; o valor NUNCA é
    interpolado, vai sempre por parâmetro."""

    def __init__(self, tipos: dict):
        self.tipos = tipos          # chave -> tipo da propriedade
        self.params: list = []

    def _p(self, v) -> str:
        self.params.append(v)
        return f"%s"

    def _lado(self, chave: str) -> tuple:
        _valida_chave(chave)
        tipo = self.tipos.get(chave, "texto")
        # colunas promovidas: título e datas de sistema não moram no jsonb
        if chave in ("titulo", "criado_em", "atualizado_em"):
            base = chave
            return base, base, base
        # A data avançada da Life guarda período, horário, lembrete e recorrência
        # num objeto. Bases antigas ainda possuem a string ISO simples. Esta
        # expressão única mantém ambos indexáveis e evita que filtros, agrupamentos
        # e ordenação mostrem `[object Object]` ou simplesmente ignorem a linha.
        if tipo == "data":
            bruto = (f"COALESCE((props->{self._p(chave)}->>'inicio'), "
                     f"(props->>{self._p(chave)}))")
        else:
            bruto = f"(props->>{self._p(chave)})"
        num = f"NULLIF({bruto},'')::numeric" if tipo in _NUMERICOS else bruto
        data = f"NULLIF({bruto},'')" if tipo in _DATAS else bruto
        return bruto, num, data

    def condicao(self, no: dict, profundidade: int = 0) -> str:
        if not isinstance(no, dict) or profundidade > 25:
            raise ErroDeConsulta("filtro inválido ou profundo demais")
        if "e" in no:
            if not isinstance(no["e"], list):
                raise ErroDeConsulta("grupo de filtro exige lista")
            partes = [self.condicao(x, profundidade + 1) for x in no["e"]]
            return "(" + " AND ".join(partes) + ")" if partes else "TRUE"
        if "ou" in no:
            if not isinstance(no["ou"], list):
                raise ErroDeConsulta("grupo de filtro exige lista")
            partes = [self.condicao(x, profundidade + 1) for x in no["ou"]]
            return "(" + " OR ".join(partes) + ")" if partes else "FALSE"
        if "nao" in no:
            return "NOT (" + self.condicao(no["nao"], profundidade + 1) + ")"

        chave = no.get("prop")
        op = no.get("op", "igual")
        if op not in _OPS:
            raise ErroDeConsulta(f"operador desconhecido: {op!r}")
        molde, precisa_valor = _OPS[op]
        if precisa_valor and "valor" not in no:
            raise ErroDeConsulta(f"operador {op} exige valor")
        if op in ("vazio", "nao_vazio") and self.tipos.get(chave) == "multi_selecao":
            _valida_chave(chave)
            vazio = f"COALESCE((props->{self._p(chave)}) IN ('null'::jsonb, '[]'::jsonb, '\"\"'::jsonb), TRUE)"
            return vazio if op == "vazio" else f"NOT ({vazio})"

        # os dois operadores de checkbox usam a chave como parâmetro nomeado
        if op in ("marcado", "desmarcado"):
            _valida_chave(chave)
            self.params.append(chave)
            return molde.replace("%(K)s", "%s")

        # A chave só entra na lista de parâmetros quando o molde cita o lado: `tem` compara o
        # jsonb inteiro e não cita, e o parâmetro a mais fazia o filtro falhar sempre.
        if any(f"{{{nome}}}" in molde for nome in ("lado", "lado_num", "lado_data")):
            bruto, num, data = self._lado(chave)
        else:
            _valida_chave(chave)
            bruto = num = data = ""
        v = no.get("valor")
        sub = {"lado": bruto, "lado_num": num, "lado_data": data}
        if precisa_valor:
            tipo = self.tipos.get(chave, "texto")
            if op == "algum_de":
                if not isinstance(v, (list, tuple)):
                    raise ErroDeConsulta("algum_de exige lista")
                sub["v_lista"] = self._p([str(x) for x in v])
            elif op == "tem":
                # JSONB containment distinguishes a scalar from an array: a
                # multi-select stores ["item"], not "item".
                if tipo == "multi_selecao" and not isinstance(v, list):
                    v = [v]
                sub["v_json"] = self._p(json.dumps({chave: v})) + "::jsonb"
            elif op == "entre":
                if not isinstance(v, (list, tuple)) or len(v) != 2:
                    raise ErroDeConsulta("entre exige [de, ate]")
                sub["v_data"] = self._p(str(v[0]))
                sub["v_data2"] = self._p(str(v[1]))
            elif op in ("contem", "nao_contem"):
                sub["v_like"] = self._p(f"%{v}%")
            elif op == "comeca_com":
                sub["v_prefixo"] = self._p(f"{v}%")
            elif op in ("maior", "maior_igual", "menor", "menor_igual"):
                sub["v_num"] = self._p(str(v)) + ("::numeric" if tipo in _NUMERICOS else "")
            elif op in ("antes", "depois"):
                sub["v_data"] = self._p(str(v))
            else:
                sub["v"] = self._p(None if v is None else str(v))
        return molde.format(**sub)


def _ordens(ordenacao, tipos) -> list:
    """One effective total order shared by SQL, cursor binding and validation."""
    if ordenacao is not None and not isinstance(ordenacao, list):
        raise ErroDeConsulta("ordenação exige lista")
    if len(ordenacao or []) > 20:
        raise ErroDeConsulta("ordenação excede 20 propriedades")
    saida, vistos = [], set()
    for o in ordenacao or []:
        if not isinstance(o, dict):
            raise ErroDeConsulta("ordenação inválida")
        chave = _valida_chave(o.get("prop"))
        direcao = str(o.get("dir", "asc")).lower()
        if direcao not in ("asc", "desc"):
            raise ErroDeConsulta("direção de ordenação inválida")
        if chave in vistos:
            continue
        vistos.add(chave)
        tipo = ("numeric" if chave == "posicao" or tipos.get(chave) in _NUMERICOS
                else "timestamp" if chave in ("criado_em", "atualizado_em") else "text")
        saida.append((chave, direcao.upper(), tipo))
    if "posicao" not in vistos:
        saida.append(("posicao", "ASC", "numeric"))
    saida.append(("id", "ASC", "uuid"))
    return saida


def _assinatura(no_id, user_id, tipos, filtro, ordens, incluir_arquivadas):
    contexto = {"no": str(no_id), "owner": str(user_id), "filtro": filtro or None,
                "ordens": ordens, "tipos": tipos, "arquivadas": bool(incluir_arquivadas)}
    try:
        bruto = json.dumps(contexto, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise ErroDeConsulta("consulta inválida")
    return hashlib.sha256(bruto.encode()).hexdigest()


def _valor_cursor(valor, tipo):
    if valor is None:
        return None
    if not isinstance(valor, str) or len(valor) > 4000:
        raise ErroDeConsulta("valor de cursor inválido")
    try:
        if tipo == "numeric":
            numero = Decimal(valor)
            if not numero.is_finite() or numero.adjusted() > 131071 or numero.as_tuple().exponent < -16383:
                raise ValueError()
            return numero
        if tipo == "timestamp":
            momento = datetime.fromisoformat(valor)
            if momento.tzinfo is None:
                raise ValueError()
            return momento
        if tipo == "uuid":
            return uuid.UUID(valor)
    except (ValueError, InvalidOperation):
        raise ErroDeConsulta("valor de cursor inválido")
    return valor


def _ler_cursor(cursor, assinatura, ordens, *, manual_sem_filtro=False):
    if not isinstance(cursor, str) or len(cursor) > 32768:
        raise ErroDeConsulta("cursor malformado")
    if not cursor.startswith("lc1."):
        # Only old unfiltered manual ASC cursors had the same ordering contract.
        # They are not accepted for filters or any explicit non-manual order.
        if not manual_sem_filtro or cursor.count("|") != 1:
            raise ErroDeConsulta("cursor antigo incompatível; atualize a vista")
        partes = cursor.split("|")
    else:
        try:
            payload = cursor[4:]
            if not re.fullmatch(r"[A-Za-z0-9_-]+", payload):
                raise ValueError()
            dados = json.loads(base64.b64decode(payload + "=" * (-len(payload) % 4), altchars=b"-_", validate=True))
            if not isinstance(dados, dict) or set(dados) != {"v", "q", "k"} or type(dados["v"]) is not int or dados["v"] != 1:
                raise ValueError()
            if dados["q"] != assinatura:
                raise ErroDeConsulta("cursor pertence a outra consulta; atualize a vista")
            partes = dados["k"]
        except (ValueError, TypeError, KeyError, binascii.Error, UnicodeDecodeError, RecursionError) as e:
            if isinstance(e, ErroDeConsulta):
                raise
            raise ErroDeConsulta("cursor malformado")
    if not isinstance(partes, list) or len(partes) != len(ordens):
        raise ErroDeConsulta("cursor não corresponde à ordenação")
    valores = [_valor_cursor(v, tipo) for v, (_, _, tipo) in zip(partes, ordens)]
    if valores[-1] is None or any(v is None for v, (chave, _, _) in zip(valores, ordens) if chave == "posicao"):
        raise ErroDeConsulta("cursor sem desempate")
    return valores


def _fingerprint_ordem(valores):
    partes = [None if v is None else v.isoformat() if isinstance(v, datetime) else str(v) for v in valores]
    return hashlib.sha256(json.dumps(partes, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def cursor_ancora(no_id, user_id, tipos, cursor, *, filtro=None, ordenacao=None, incluir_arquivadas=False):
    if not cursor or not isinstance(cursor, str) or not cursor.startswith("lc2."):
        return None
    try:
        if len(cursor) > 1024:
            raise ValueError()
        payload = cursor[4:]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", payload):
            raise ValueError()
        dados = json.loads(base64.b64decode(payload + "=" * (-len(payload) % 4), altchars=b"-_", validate=True))
        if not isinstance(dados, dict) or set(dados) != {"v", "q", "a", "f"} or type(dados["v"]) is not int or dados["v"] != 2:
            raise ValueError()
        if dados["q"] != _assinatura(no_id, user_id, tipos, filtro, _ordens(ordenacao, tipos), incluir_arquivadas):
            raise ErroDeConsulta("cursor pertence a outra consulta; atualize a vista")
        ident = str(uuid.UUID(dados["a"]))
        if not isinstance(dados["f"], str) or not re.fullmatch(r"[a-f0-9]{64}", dados["f"]):
            raise ValueError()
        return ident, dados["f"]
    except (ValueError, TypeError, KeyError, AttributeError, binascii.Error, UnicodeDecodeError, RecursionError) as e:
        if isinstance(e, ErroDeConsulta):
            raise
        raise ErroDeConsulta("cursor malformado")


def gerar_cursor(no_id, user_id, tipos, linha, *, filtro=None, ordenacao=None, incluir_arquivadas=False):
    """Opaque query-bound cursor from the exact DB ordering values, never floats."""
    ordens = _ordens(ordenacao, tipos)
    valores = linha[8:]
    if len(valores) != len(ordens):
        raise ErroDeConsulta("resultado sem valores de ordenação")
    dados = {"v": 2, "q": _assinatura(no_id, user_id, tipos, filtro, ordens, incluir_arquivadas),
             "a": str(linha[0]), "f": _fingerprint_ordem(valores)}
    return "lc2." + base64.urlsafe_b64encode(json.dumps(dados, separators=(",", ":")).encode()).decode().rstrip("=")


def montar(no_id: str, user_id: str, tipos: dict, *, filtro=None, ordenacao=None,
           limite: int = 50, cursor: Optional[str] = None,
           incluir_arquivadas: bool = False, ancora_id: Optional[str] = None,
           ancora: Optional[tuple] = None) -> tuple:
    """Devolve (sql, params). Limite tem teto: nada de resposta sem fim."""
    limite = max(1, min(int(limite or 50), 200))
    m = _Montador(tipos)
    onde = ["no_id = %s", "user_id = %s", "deletado_em IS NULL"]
    # os dois primeiros parâmetros vêm antes de qualquer coisa que o montador crie
    cabeca = [no_id, user_id]
    if ancora_id is not None:
        onde.append("id = %s::uuid")
        cabeca.append(ancora_id)
    if not incluir_arquivadas:
        onde.append("arquivado_em IS NULL")
    corpo = m.condicao(filtro) if filtro else "TRUE"
    onde.append(corpo)
    ordens = _ordens(ordenacao, tipos)
    sort = _Montador(tipos)
    expressoes, aliases, pedacos = [], [], []
    for i, (chave, direcao, tipo) in enumerate(ordens):
        alias = f"_ord{i}"
        if chave in ("posicao", "id", "titulo", "criado_em", "atualizado_em"):
            alvo = chave
        else:
            bruto, num, data = sort._lado(chave)
            alvo = num if tipo == "numeric" else data if tipos.get(chave) in _DATAS else bruto
        expressoes.append(f"{alvo} AS {alias}")
        aliases.append(alias)
        pedacos.append(f"{alias} {direcao} NULLS LAST")
    continuacao, params_cursor = "TRUE", []
    if cursor:
        assinatura = _assinatura(no_id, user_id, tipos, filtro, ordens, incluir_arquivadas)
        info = cursor_ancora(no_id, user_id, tipos, cursor, filtro=filtro, ordenacao=ordenacao, incluir_arquivadas=incluir_arquivadas)
        if info:
            if not ancora or str(ancora[0]) != info[0] or len(ancora[8:]) != len(ordens) or _fingerprint_ordem(ancora[8:]) != info[1]:
                raise ErroDeCursorExpirado("a âncora da página mudou; atualize a vista")
            valores = list(ancora[8:])
        else:
            valores = _ler_cursor(cursor, assinatura, ordens,
                                  manual_sem_filtro=not filtro and ordens == [("posicao", "ASC", "numeric"), ("id", "ASC", "uuid")])
        partes = []
        # Lexicographic keyset with mixed directions and NULLS LAST. Tuple >
        # cannot express DESC or a boundary whose primary value is NULL.
        for i, ((_, direcao, _), valor) in enumerate(zip(ordens, valores)):
            if valor is None:
                continue
            anteriores = []
            for j in range(i):
                anteriores.append(f"{aliases[j]} IS NOT DISTINCT FROM %s")
                params_cursor.append(valores[j])
            op = ">" if direcao == "ASC" else "<"
            anteriores.append(f"({aliases[i]} {op} %s OR {aliases[i]} IS NULL)")
            params_cursor.append(valor)
            partes.append("(" + " AND ".join(anteriores) + ")")
        continuacao = "(" + " OR ".join(partes) + ")" if partes else "FALSE"
    colunas = "id, no_id, titulo, props, posicao, criado_em, atualizado_em, arquivado_em"
    sql = (f"WITH candidatas AS (SELECT {colunas}, " + ", ".join(expressoes) +
           " FROM banco.linha WHERE " + " AND ".join(onde) +
           f") SELECT {colunas}, " + ", ".join(aliases) + " FROM candidatas WHERE " + continuacao +
           " ORDER BY " + ", ".join(pedacos) + " LIMIT %s")
    # +1 para saber se existe próxima página sem um COUNT separado
    return sql, sort.params + cabeca + m.params + params_cursor + [limite + 1]


def montar_contagem_por_grupo(no_id: str, user_id: str, tipos: dict, agrupar_por: str,
                              filtro=None, incluir_arquivadas: bool = False) -> tuple:
    """Quadro e calendário precisam do total por coluna e por dia SEM carregar as
    linhas. Sem isto, a única forma de mostrar '40' no cabeçalho da coluna seria
    buscar as 40, que é o oposto de paginar."""
    m = _Montador(tipos)
    # A expressão de agrupamento é montada PRIMEIRO porque ela aparece no SELECT, que
    # vem ANTES do WHERE no texto do SQL. Montá-la depois do filtro colocaria o
    # parâmetro dela no fim da lista enquanto o marcador está no começo da consulta:
    # o Postgres casaria a chave da propriedade com o valor do primeiro filtro, sem
    # dar erro, e o agrupamento devolveria contagem de outra coluna.
    bruto_grupo, _, _ = m._lado(agrupar_por)
    grupo_params = list(m.params)
    m.params = []
    onde = ["no_id = %s", "user_id = %s", "deletado_em IS NULL"]
    if not incluir_arquivadas:
        onde.append("arquivado_em IS NULL")
    if filtro:
        onde.append(m.condicao(filtro))
    sql = (f"SELECT COALESCE({bruto_grupo}, '') AS grupo, COUNT(*) FROM banco.linha "
           f"WHERE " + " AND ".join(onde) + " GROUP BY 1 ORDER BY 2 DESC LIMIT 200")
    return sql, grupo_params + [no_id, user_id] + m.params
