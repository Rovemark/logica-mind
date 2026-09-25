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
from typing import Any, Optional

_CHAVE_OK = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

# op -> (molde SQL, precisa de valor)
_OPS = {
    "igual":        ("{lado} = {v}", True),
    "diferente":    ("({lado} IS DISTINCT FROM {v})", True),
    "contem":       ("{lado} ILIKE {v_like}", True),
    "nao_contem":   ("({lado} IS NULL OR {lado} NOT ILIKE {v_like})", True),
    "comeca_com":   ("{lado} ILIKE {v_prefixo}", True),
    "vazio":        ("({lado} IS NULL OR {lado} = '')", False),
    "nao_vazio":    ("({lado} IS NOT NULL AND {lado} <> '')", False),
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


def _valida_chave(chave: str) -> str:
    if not isinstance(chave, str) or not _CHAVE_OK.match(chave):
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

    def condicao(self, no: dict) -> str:
        if "e" in no:
            partes = [self.condicao(x) for x in no["e"]]
            return "(" + " AND ".join(partes) + ")" if partes else "TRUE"
        if "ou" in no:
            partes = [self.condicao(x) for x in no["ou"]]
            return "(" + " OR ".join(partes) + ")" if partes else "FALSE"
        if "nao" in no:
            return "NOT (" + self.condicao(no["nao"]) + ")"

        chave = no.get("prop")
        op = no.get("op", "igual")
        if op not in _OPS:
            raise ErroDeConsulta(f"operador desconhecido: {op!r}")
        molde, precisa_valor = _OPS[op]
        if precisa_valor and "valor" not in no:
            raise ErroDeConsulta(f"operador {op} exige valor")

        # os dois operadores de checkbox usam a chave como parâmetro nomeado
        if op in ("marcado", "desmarcado"):
            _valida_chave(chave)
            self.params.append(chave)
            return molde.replace("%(K)s", "%s")

        bruto, num, data = self._lado(chave)
        v = no.get("valor")
        sub = {"lado": bruto, "lado_num": num, "lado_data": data}
        if precisa_valor:
            tipo = self.tipos.get(chave, "texto")
            if op == "algum_de":
                if not isinstance(v, (list, tuple)):
                    raise ErroDeConsulta("algum_de exige lista")
                sub["v_lista"] = self._p([str(x) for x in v])
            elif op == "tem":
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


def _ordenacao_sql(ordenacao, tipos, m: _Montador) -> str:
    """ORDER BY seguro. Sem ordenação explícita, a ordem é a manual (`posicao`),
    que é o que o usuário arrastou. `id` entra sempre no fim como desempate estável:
    sem ele, duas linhas com a mesma posição podem trocar de lugar entre páginas e a
    paginação por cursor pula ou repete linha."""
    pedacos = []
    for o in (ordenacao or []):
        chave = o.get("prop")
        direcao = "DESC" if str(o.get("dir", "asc")).lower() == "desc" else "ASC"
        nulos = "NULLS LAST" if direcao == "ASC" else "NULLS LAST"
        if chave in ("posicao", "criado_em", "atualizado_em", "titulo"):
            pedacos.append(f"{chave} {direcao} {nulos}")
            continue
        bruto, num, data = m._lado(chave)
        tipo = tipos.get(chave, "texto")
        alvo = num if tipo in _NUMERICOS else (data if tipo in _DATAS else bruto)
        pedacos.append(f"{alvo} {direcao} {nulos}")
    pedacos.append("posicao ASC")
    pedacos.append("id ASC")
    return ", ".join(pedacos)


def montar(no_id: str, user_id: str, tipos: dict, *, filtro=None, ordenacao=None,
           limite: int = 50, cursor: Optional[str] = None,
           incluir_arquivadas: bool = False) -> tuple:
    """Devolve (sql, params). Limite tem teto: nada de resposta sem fim."""
    limite = max(1, min(int(limite or 50), 200))
    m = _Montador(tipos)
    onde = ["no_id = %s", "user_id = %s", "deletado_em IS NULL"]
    # os dois primeiros parâmetros vêm antes de qualquer coisa que o montador crie
    cabeca = [no_id, user_id]
    if not incluir_arquivadas:
        onde.append("arquivado_em IS NULL")
    corpo = m.condicao(filtro) if filtro else "TRUE"
    onde.append(corpo)
    if cursor:
        # keyset em (posicao, id): OFFSET fica lento e pula linha quando alguém
        # insere durante a paginação.
        try:
            pos, ident = cursor.split("|", 1)
        except ValueError:
            raise ErroDeConsulta("cursor malformado")
        onde.append("(posicao, id) > (%s::numeric, %s::uuid)")
        m.params += [pos, ident]
    ordem = _ordenacao_sql(ordenacao, tipos, m)
    sql = (f"SELECT id, no_id, titulo, props, posicao, criado_em, atualizado_em, arquivado_em "
           f"FROM banco.linha WHERE " + " AND ".join(onde) +
           f" ORDER BY {ordem} LIMIT %s")
    # +1 para saber se existe próxima página sem um COUNT separado
    return sql, cabeca + m.params + [limite + 1]


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
