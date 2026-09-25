"""Operações do Banco de dados: criar, mover, editar, apagar. E o índice sob demanda.

Duas coisas aqui merecem explicação porque parecem detalhe e não são.

POSIÇÃO POR PONTO MÉDIO. `posicao` é `numeric` (precisão arbitrária). Inserir entre
dois vizinhos é a média dos dois. Arrastar um item para o topo de uma lista de 300
escreve UMA linha; com inteiro sequencial, escreveria 300, a cada gesto. O custo
conhecido é a escala crescer depois de muitas reordenações no mesmo ponto, e por isso
existe `recompactar`, que roda fora do caminho quente.

ÍNDICE SOB DEMANDA. O GIN em `props` serve `@>`, e só. Filtro de faixa e ordenação não
usam GIN: um calendário filtrando por mês varreria a base inteira. Quando o usuário
salva uma vista que filtra ou ordena por uma propriedade, `garantir_indice` cria um
btree de expressão para aquela base e aquela chave. Riscos reais disso, e o que os
contém: DDL a partir de entrada do usuário (a chave já passou pelo CHECK do banco e é
revalidada aqui), explosão de índices (teto por base), e `CONCURRENTLY` que não roda em
transação e pode deixar índice inválido (roda fora do request, e há varredura de
`indisvalid`).
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any, Optional

from .esquema import TIPOS, ATRIBUTOS
from .consulta import _CHAVE_OK, ErroDeConsulta

TETO_INDICES_POR_BASE = 6
_PASSO = 1000.0


class ErroDeBanco(ValueError):
    pass


def _uid() -> str:
    return str(uuid.uuid4())


def _s(v):
    """psycopg devolve uuid/timestamp como OBJETO, não como texto. Isso não dá erro
    em consulta (o driver sabe adaptar de volta), mas explode em qualquer operação de
    texto e serializa errado no JSON. Coagir na saída é mais barato que lembrar disso
    em cada ponto de uso."""
    return None if v is None else str(v)


def _slug(nome: str, usados: set) -> str:
    """Nome vira chave: minúsculo, sem acento, com sublinhado. A chave é ENDEREÇO e
    não muda nunca; o nome é rótulo e pode virar o que o usuário quiser."""
    import unicodedata
    s = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    s = re.sub(r"^[^a-z]+", "", s) or "campo"
    s = s[:40]
    if s not in usados:
        return s
    i = 2
    while f"{s[:37]}_{i}" in usados:
        i += 1
    return f"{s[:37]}_{i}"


# ── posição ───────────────────────────────────────────────────────────────────
def posicao_para(cur, tabela: str, coluna_pai: str, pai_id: str, user_id: str,
                 antes_de: Optional[str] = None, depois_de: Optional[str] = None) -> float:
    """Ponto médio entre os vizinhos. Sem vizinho, empilha no fim."""
    def pos_de(ident):
        cur.execute(f"SELECT posicao FROM banco.{tabela} WHERE id=%s AND user_id=%s",
                    (ident, user_id))
        r = cur.fetchone()
        return float(r[0]) if r else None

    p_antes = pos_de(antes_de) if antes_de else None
    p_depois = pos_de(depois_de) if depois_de else None
    if p_antes is not None and p_depois is not None:
        return (p_antes + p_depois) / 2.0
    if p_antes is not None:      # entrar logo ANTES de X
        cur.execute(f"SELECT max(posicao) FROM banco.{tabela} "
                    f"WHERE {coluna_pai}=%s AND user_id=%s AND posicao < %s",
                    (pai_id, user_id, p_antes))
        anterior = cur.fetchone()[0]
        return (float(anterior) + p_antes) / 2.0 if anterior is not None else p_antes - _PASSO
    if p_depois is not None:     # entrar logo DEPOIS de X
        cur.execute(f"SELECT min(posicao) FROM banco.{tabela} "
                    f"WHERE {coluna_pai}=%s AND user_id=%s AND posicao > %s",
                    (pai_id, user_id, p_depois))
        seguinte = cur.fetchone()[0]
        return (float(seguinte) + p_depois) / 2.0 if seguinte is not None else p_depois + _PASSO
    cur.execute(f"SELECT COALESCE(max(posicao), 0) FROM banco.{tabela} "
                f"WHERE {coluna_pai}=%s AND user_id=%s", (pai_id, user_id))
    return float(cur.fetchone()[0]) + _PASSO


def recompactar(cur, tabela: str, coluna_pai: str, pai_id: str, user_id: str) -> int:
    """Reatribui 1000, 2000, 3000… preservando a ordem. O ponto médio faz a escala
    crescer depois de muitas reordenações no mesmo ponto; isto devolve folga. Não
    roda no caminho de request."""
    cur.execute(f"SELECT id FROM banco.{tabela} WHERE {coluna_pai}=%s AND user_id=%s "
                "ORDER BY posicao, id", (pai_id, user_id))
    ids = [r[0] for r in cur.fetchall()]
    for i, ident in enumerate(ids, start=1):
        cur.execute(f"UPDATE banco.{tabela} SET posicao=%s WHERE id=%s", (i * _PASSO, ident))
    return len(ids)


# ── espaço e árvore ───────────────────────────────────────────────────────────
def criar_espaco(cur, user_id: str, nome: str, icone: str = None) -> dict:
    ident = _uid()
    cur.execute("INSERT INTO banco.espaco (id,user_id,nome,icone,ordem) "
                "VALUES (%s,%s,%s,%s,(SELECT COALESCE(max(ordem),0)+1000 FROM banco.espaco WHERE user_id=%s)) "
                "RETURNING id,nome,icone,ordem", (ident, user_id, nome, icone, user_id))
    r = cur.fetchone()
    return {"id": _s(r[0]), "nome": r[1], "icone": r[2], "ordem": float(r[3])}


def espaco_padrao(cur, user_id: str) -> str:
    """Todo usuário tem um espaço. Criar sob demanda evita a tela vazia do primeiro
    acesso, que é onde produto novo perde gente."""
    cur.execute("SELECT id FROM banco.espaco WHERE user_id=%s AND arquivado_em IS NULL "
                "ORDER BY ordem LIMIT 1", (user_id,))
    r = cur.fetchone()
    return _s(r[0]) if r else criar_espaco(cur, user_id, "Minha vida", "◈")["id"]


def criar_no(cur, user_id: str, *, espaco_id: str = None, pai_id: str = None,
             tipo: str = "pagina", nome: str = "Sem título", icone: str = None,
             modelo: str = None, chave_titulo: str = None) -> dict:
    if tipo not in ("pagina", "banco"):
        raise ErroDeBanco("tipo de nó tem que ser pagina ou banco")
    if not espaco_id:
        if pai_id:
            cur.execute("SELECT espaco_id FROM banco.no WHERE id=%s AND user_id=%s", (pai_id, user_id))
            r = cur.fetchone()
            if not r:
                raise ErroDeBanco("nó pai não encontrado")
            espaco_id = _s(r[0])
        else:
            espaco_id = espaco_padrao(cur, user_id)
    # A posição é resolvida aqui, e não por posicao_para(), porque o "pai" de um nó
    # muda de coluna: nó de topo pendura no espaço, nó aninhado pendura no pai. Uma
    # função genérica precisaria de coluna calculada e não usaria o índice.
    cur.execute("SELECT COALESCE(max(posicao),0)+%s FROM banco.no "
                "WHERE user_id=%s AND espaco_id=%s AND pai_id IS NOT DISTINCT FROM %s",
                (_PASSO, user_id, espaco_id, pai_id))
    pos = float(cur.fetchone()[0])
    ident = _uid()
    cur.execute("INSERT INTO banco.no (id,espaco_id,user_id,pai_id,tipo,nome,icone,modelo,chave_titulo,posicao) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (ident, espaco_id, user_id, pai_id, tipo, nome, icone, modelo,
                 chave_titulo or ("titulo" if tipo == "banco" else None), pos))
    return {"id": _s(cur.fetchone()[0]), "espaco_id": _s(espaco_id), "pai_id": _s(pai_id),
            "tipo": tipo, "nome": nome, "icone": icone, "posicao": pos}


def mover_no(cur, user_id: str, no_id: str, *, pai_id: str = None,
             antes_de: str = None, depois_de: str = None) -> float:
    cur.execute("SELECT espaco_id FROM banco.no WHERE id=%s AND user_id=%s", (no_id, user_id))
    r = cur.fetchone()
    if not r:
        raise ErroDeBanco("nó não encontrado")
    espaco_id = _s(r[0])
    # ciclo na árvore: mover um nó para dentro do próprio descendente deixaria um
    # ramo órfão que some da barra lateral sem apagar nada. O banco não pega isso.
    if pai_id:
        alvo = _s(pai_id)
        for _ in range(64):
            if alvo == _s(no_id):
                raise ErroDeBanco("mover para dentro do próprio ramo criaria ciclo")
            cur.execute("SELECT pai_id FROM banco.no WHERE id=%s AND user_id=%s", (alvo, user_id))
            rr = cur.fetchone()
            if not rr or not rr[0]:
                break
            alvo = _s(rr[0])
    pos = posicao_para(cur, "no", "pai_id", pai_id, user_id, antes_de, depois_de) \
        if pai_id else _pos_topo(cur, user_id, espaco_id, antes_de, depois_de)
    cur.execute("UPDATE banco.no SET pai_id=%s, posicao=%s, atualizado_em=now() "
                "WHERE id=%s AND user_id=%s", (pai_id, pos, no_id, user_id))
    return pos


def _pos_topo(cur, user_id, espaco_id, antes_de, depois_de) -> float:
    def pos_de(i):
        if not i:
            return None
        cur.execute("SELECT posicao FROM banco.no WHERE id=%s AND user_id=%s", (i, user_id))
        r = cur.fetchone()
        return float(r[0]) if r else None
    a, d = pos_de(antes_de), pos_de(depois_de)
    if a is not None and d is not None:
        return (a + d) / 2.0
    if a is not None:
        return a - _PASSO / 2
    if d is not None:
        return d + _PASSO / 2
    cur.execute("SELECT COALESCE(max(posicao),0)+%s FROM banco.no "
                "WHERE user_id=%s AND espaco_id=%s AND pai_id IS NULL", (_PASSO, user_id, espaco_id))
    return float(cur.fetchone()[0])


# ── esquema do banco do usuário ───────────────────────────────────────────────
def criar_propriedade(cur, user_id: str, no_id: str, nome: str, tipo: str,
                      config: dict = None, chave: str = None) -> dict:
    if tipo not in TIPOS:
        raise ErroDeBanco(f"tipo de propriedade desconhecido: {tipo}")
    cur.execute("SELECT chave FROM banco.propriedade WHERE no_id=%s", (no_id,))
    usados = {r[0] for r in cur.fetchall()}
    chave = chave or _slug(nome, usados)
    if not _CHAVE_OK.match(chave):
        raise ErroDeBanco(f"chave inválida: {chave!r}")
    if chave in usados:
        raise ErroDeBanco(f"chave já existe nesta base: {chave!r}")
    ident = _uid()
    cur.execute("INSERT INTO banco.propriedade (id,no_id,user_id,chave,nome,tipo,config,ordem) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,"
                "(SELECT COALESCE(max(ordem),0)+1000 FROM banco.propriedade WHERE no_id=%s)) "
                "RETURNING id,ordem",
                (ident, no_id, user_id, chave, nome, tipo, json.dumps(config or {}), no_id))
    r = cur.fetchone()
    return {"id": _s(r[0]), "chave": chave, "nome": nome, "tipo": tipo,
            "config": config or {}, "ordem": float(r[1])}


def propriedades(cur, user_id: str, no_id: str) -> list:
    cur.execute("SELECT id,chave,nome,tipo,config,ordem,oculta FROM banco.propriedade "
                "WHERE no_id=%s AND user_id=%s ORDER BY ordem, chave", (no_id, user_id))
    return [{"id": _s(i), "chave": c, "nome": n, "tipo": t, "config": cf,
             "ordem": float(o), "oculta": oc} for i, c, n, t, cf, o, oc in cur.fetchall()]


def tipos_de(props: list) -> dict:
    d = {p["chave"]: p["tipo"] for p in props}
    d["titulo"] = "texto"
    return d


def criar_vista(cur, user_id: str, no_id: str, nome: str, tipo: str,
                config: dict = None, padrao: bool = False) -> dict:
    ident = _uid()
    if padrao:
        cur.execute("UPDATE banco.vista SET padrao=false WHERE no_id=%s AND user_id=%s",
                    (no_id, user_id))
    cur.execute("INSERT INTO banco.vista (id,no_id,user_id,nome,tipo,config,ordem,padrao) "
                "VALUES (%s,%s,%s,%s,%s,%s,"
                "(SELECT COALESCE(max(ordem),0)+1000 FROM banco.vista WHERE no_id=%s),%s) "
                "RETURNING id,ordem",
                (ident, no_id, user_id, nome, tipo, json.dumps(config or {}), no_id, padrao))
    r = cur.fetchone()
    return {"id": _s(r[0]), "nome": nome, "tipo": tipo, "config": config or {},
            "ordem": float(r[1]), "padrao": padrao}


def vistas(cur, user_id: str, no_id: str) -> list:
    cur.execute("SELECT id,nome,tipo,config,ordem,padrao FROM banco.vista "
                "WHERE no_id=%s AND user_id=%s ORDER BY ordem", (no_id, user_id))
    return [{"id": _s(i), "nome": n, "tipo": t, "config": c, "ordem": float(o), "padrao": p}
            for i, n, t, c, o, p in cur.fetchall()]


# ── linhas ────────────────────────────────────────────────────────────────────
def _titulo_de(cur, user_id: str, no_id: str, props: dict) -> str:
    cur.execute("SELECT chave_titulo FROM banco.no WHERE id=%s AND user_id=%s", (no_id, user_id))
    r = cur.fetchone()
    chave = (r[0] if r else None) or "titulo"
    v = props.get(chave)
    if isinstance(v, (list, dict)):
        v = json.dumps(v, ensure_ascii=False)
    return ("" if v is None else str(v))[:400]


def criar_linha(cur, user_id: str, no_id: str, props: dict = None,
                antes_de: str = None, depois_de: str = None) -> dict:
    props = props or {}
    titulo = props.pop("titulo", None)
    if titulo is None:
        titulo = _titulo_de(cur, user_id, no_id, props)
    pos = posicao_para(cur, "linha", "no_id", no_id, user_id, antes_de, depois_de)
    ident = _uid()
    cur.execute("INSERT INTO banco.linha (id,no_id,user_id,titulo,props,posicao) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id,criado_em",
                (ident, no_id, user_id, str(titulo)[:400], json.dumps(props), pos))
    r = cur.fetchone()
    return {"id": _s(r[0]), "no_id": _s(no_id), "titulo": titulo, "props": props,
            "posicao": pos, "criado_em": r[1].isoformat()}


def atualizar_linha(cur, user_id: str, linha_id: str, mudancas: dict) -> dict:
    """Mescla parcial: só as chaves enviadas mudam. Enviar o objeto inteiro seria
    perder o que outra aba escreveu entre a leitura e a gravação."""
    cur.execute("SELECT no_id, props, titulo FROM banco.linha "
                "WHERE id=%s AND user_id=%s AND deletado_em IS NULL", (linha_id, user_id))
    r = cur.fetchone()
    if not r:
        raise ErroDeBanco("linha não encontrada")
    no_id, atuais, titulo_atual = _s(r[0]), dict(r[1] or {}), r[2]
    novo_titulo = mudancas.pop("titulo", None)
    for k, v in mudancas.items():
        if v is None:
            atuais.pop(k, None)
        else:
            atuais[k] = v
    titulo = novo_titulo if novo_titulo is not None else _titulo_de(cur, user_id, no_id, atuais)
    if not titulo:
        titulo = titulo_atual
    cur.execute("UPDATE banco.linha SET props=%s, titulo=%s, atualizado_em=now() "
                "WHERE id=%s AND user_id=%s RETURNING atualizado_em",
                (json.dumps(atuais), str(titulo)[:400], linha_id, user_id))
    return {"id": _s(linha_id), "no_id": no_id, "props": atuais, "titulo": titulo,
            "atualizado_em": cur.fetchone()[0].isoformat()}


def mover_linha(cur, user_id: str, linha_id: str, antes_de: str = None,
                depois_de: str = None) -> float:
    cur.execute("SELECT no_id FROM banco.linha WHERE id=%s AND user_id=%s", (linha_id, user_id))
    r = cur.fetchone()
    if not r:
        raise ErroDeBanco("linha não encontrada")
    pos = posicao_para(cur, "linha", "no_id", _s(r[0]), user_id, antes_de, depois_de)
    cur.execute("UPDATE banco.linha SET posicao=%s, atualizado_em=now() "
                "WHERE id=%s AND user_id=%s", (pos, linha_id, user_id))
    return pos


def apagar_linha(cur, user_id: str, linha_id: str) -> bool:
    """Lixeira, não DELETE. Apagar de verdade acontece na varredura dos 30 dias."""
    cur.execute("UPDATE banco.linha SET deletado_em=now() "
                "WHERE id=%s AND user_id=%s AND deletado_em IS NULL", (linha_id, user_id))
    return cur.rowcount > 0


def restaurar_linha(cur, user_id: str, linha_id: str) -> bool:
    cur.execute("UPDATE banco.linha SET deletado_em=NULL "
                "WHERE id=%s AND user_id=%s AND deletado_em IS NOT NULL", (linha_id, user_id))
    return cur.rowcount > 0


def excluir_linha_definitivamente(cur, user_id: str, linha_id: str) -> bool:
    """Exclui somente itens que já estão na lixeira.

    A condição em `deletado_em` impede que esta rota vire um atalho acidental para
    apagar uma linha ativa sem passar pela etapa recuperável.
    """
    cur.execute("DELETE FROM banco.linha WHERE id=%s AND user_id=%s "
                "AND deletado_em IS NOT NULL", (linha_id, user_id))
    return cur.rowcount > 0


def esvaziar_lixeira(cur, user_id: str, dias: int = 30) -> int:
    cur.execute("DELETE FROM banco.linha WHERE user_id=%s AND deletado_em IS NOT NULL "
                "AND deletado_em < now() - make_interval(days => %s)", (user_id, int(dias)))
    return cur.rowcount


# ── documento ─────────────────────────────────────────────────────────────────
def salvar_documento(cur, user_id: str, *, no_id: str = None, linha_id: str = None,
                     doc: dict, texto: str, versao_base: int = None) -> dict:
    """Gravação com versão. Duas abas abertas comeriam uma à outra em silêncio, e a
    perda só apareceria dias depois: por isso a versão vem no pedido e divergência
    devolve conflito em vez de sobrescrever."""
    if (no_id is None) == (linha_id is None):
        raise ErroDeBanco("documento pertence a um nó OU a uma linha")
    col = "no_id" if no_id else "linha_id"
    alvo = no_id or linha_id
    cur.execute(f"SELECT id, versao FROM banco.documento WHERE {col}=%s AND user_id=%s",
                (alvo, user_id))
    r = cur.fetchone()
    if r is None:
        ident = _uid()
        cur.execute(f"INSERT INTO banco.documento (id,user_id,{col},doc,texto,versao) "
                    "VALUES (%s,%s,%s,%s,%s,1) RETURNING versao",
                    (ident, user_id, alvo, json.dumps(doc), texto[:2_000_000]))
        nova_versao = cur.fetchone()[0]
        _registrar_revisao(cur, user_id, ident, no_id=no_id, linha_id=linha_id,
                           versao=nova_versao, doc=doc, texto=texto)
        if no_id:
            _sincronizar_referencias(cur, user_id, no_id, doc)
        return {"id": _s(ident), "versao": nova_versao, "conflito": False}
    ident, versao = _s(r[0]), r[1]
    if versao_base is not None and int(versao_base) != versao:
        return {"id": _s(ident), "versao": versao, "conflito": True}
    cur.execute("UPDATE banco.documento SET doc=%s, texto=%s, versao=versao+1, "
                "atualizado_em=now() WHERE id=%s AND user_id=%s RETURNING versao",
                (json.dumps(doc), texto[:2_000_000], ident, user_id))
    nova_versao = cur.fetchone()[0]
    _registrar_revisao(cur, user_id, ident, no_id=no_id, linha_id=linha_id,
                       versao=nova_versao, doc=doc, texto=texto)
    if no_id:
        _sincronizar_referencias(cur, user_id, no_id, doc)
    return {"id": _s(ident), "versao": nova_versao, "conflito": False}


def _sincronizar_referencias(cur, user_id: str, origem_no_id: str, doc: dict):
    """Reconstrói o índice de backlinks da página na mesma transação do documento."""
    encontradas = set()

    def visitar(no, bloco_pai=None):
        if not isinstance(no, dict):
            return
        attrs = no.get("attrs") if isinstance(no.get("attrs"), dict) else {}
        bloco = attrs.get("blockId") or bloco_pai
        tipo = no.get("type")
        if tipo == "mention" and attrs.get("id"):
            encontradas.add((str(attrs["id"]), str(bloco) if bloco else None, "mention"))
        elif tipo == "lifePageLink" and attrs.get("noId"):
            encontradas.add((str(attrs["noId"]), str(bloco) if bloco else None, "pagina"))
        for filho in no.get("content") or []:
            visitar(filho, bloco)

    visitar(doc)
    cur.execute("DELETE FROM banco.referencia_pagina WHERE user_id=%s AND origem_no_id=%s",
                (user_id, origem_no_id))
    if not encontradas:
        return
    destinos = [destino for destino, _, _ in encontradas]
    cur.execute("SELECT id::text FROM banco.no WHERE user_id=%s AND id::text=ANY(%s) ",
                (user_id, destinos))
    permitidos = {r[0] for r in cur.fetchall()}
    valores = [(_uid(), user_id, origem_no_id, destino, bloco, tipo)
               for destino, bloco, tipo in encontradas
               if destino in permitidos and destino != str(origem_no_id)]
    if valores:
        cur.executemany("INSERT INTO banco.referencia_pagina "
                        "(id,user_id,origem_no_id,destino_no_id,block_id,tipo) "
                        "VALUES (%s,%s,%s,%s,%s,%s)", valores)


def listar_backlinks(cur, user_id: str, no_id: str):
    cur.execute("SELECT r.origem_no_id,n.nome,n.icone,r.block_id,r.tipo "
                "FROM banco.referencia_pagina r "
                "JOIN banco.no n ON n.id=r.origem_no_id AND n.user_id=r.user_id "
                "WHERE r.user_id=%s AND r.destino_no_id=%s AND n.arquivado_em IS NULL "
                "ORDER BY n.atualizado_em DESC,r.criado_em ASC LIMIT 500",
                (user_id, no_id))
    return [{"origem_id": _s(r[0]), "nome": r[1], "icone": r[2],
             "block_id": r[3], "tipo": r[4]} for r in cur.fetchall()]


def _registrar_revisao(cur, user_id, documento_id, *, no_id=None, linha_id=None,
                       versao: int, doc: dict, texto: str):
    cur.execute("INSERT INTO banco.revisao_documento "
                "(user_id,documento_id,no_id,linha_id,versao,doc,texto,autor_id) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (documento_id,versao) DO NOTHING",
                (user_id, documento_id, no_id, linha_id, versao, json.dumps(doc),
                 (texto or '')[:2_000_000], user_id))
    # Retenção inicial equivalente ao plano normal do Notion: últimas 100 versões.
    cur.execute("DELETE FROM banco.revisao_documento WHERE documento_id=%s AND id NOT IN "
                "(SELECT id FROM banco.revisao_documento WHERE documento_id=%s "
                "ORDER BY versao DESC LIMIT 100)", (documento_id, documento_id))


def ler_documento(cur, user_id: str, *, no_id: str = None, linha_id: str = None):
    col = "no_id" if no_id else "linha_id"
    alvo = no_id or linha_id
    cur.execute(f"SELECT id,doc,versao,atualizado_em FROM banco.documento "
                f"WHERE {col}=%s AND user_id=%s", (alvo, user_id))
    r = cur.fetchone()
    if not r:
        return {"id": None, "doc": {"type": "doc", "content": []}, "versao": 0}
    return {"id": _s(r[0]), "doc": r[1], "versao": r[2], "atualizado_em": r[3].isoformat()}


def listar_revisoes(cur, user_id: str, *, no_id: str = None, linha_id: str = None):
    col, alvo = ("no_id", no_id) if no_id else ("linha_id", linha_id)
    cur.execute(f"SELECT r.id,r.versao,r.autor_id,r.criado_em,left(r.texto,300) "
                f"FROM banco.revisao_documento r WHERE r.{col}=%s AND r.user_id=%s "
                "ORDER BY r.versao DESC LIMIT 100", (alvo, user_id))
    return [{"id": r[0], "versao": r[1], "autor_id": r[2],
             "criado_em": r[3].isoformat(), "resumo": r[4]} for r in cur.fetchall()]


def restaurar_revisao(cur, user_id: str, revisao_id: int, versao_base=None):
    cur.execute("SELECT r.documento_id,r.no_id,r.linha_id,r.doc,r.texto,d.versao "
                "FROM banco.revisao_documento r JOIN banco.documento d ON d.id=r.documento_id "
                "WHERE r.id=%s AND r.user_id=%s AND d.user_id=%s FOR UPDATE",
                (revisao_id, user_id, user_id))
    r = cur.fetchone()
    if not r:
        raise ErroDeBanco("revisão não encontrada")
    documento_id, no_id, linha_id, doc, texto, atual = r
    if versao_base is not None and int(versao_base) != atual:
        raise ErroDeBanco("a página mudou; atualize o histórico antes de restaurar")
    nova = atual + 1
    cur.execute("UPDATE banco.documento SET doc=%s,texto=%s,versao=%s,atualizado_em=now() "
                "WHERE id=%s AND user_id=%s", (json.dumps(doc), texto, nova, documento_id, user_id))
    _registrar_revisao(cur, user_id, documento_id, no_id=no_id, linha_id=linha_id,
                       versao=nova, doc=doc, texto=texto)
    if no_id:
        _sincronizar_referencias(cur, user_id, _s(no_id), doc)
    return {"id": _s(documento_id), "versao": nova, "doc": doc}


def listar_comentarios(cur, user_id: str, *, no_id=None, linha_id=None,
                       incluir_resolvidos=False):
    col, alvo = ("no_id", no_id) if no_id else ("linha_id", linha_id)
    extra = "" if incluir_resolvidos else " AND resolvido_em IS NULL"
    cur.execute(f"SELECT id,block_id,pai_id,autor_id,corpo,criado_em,atualizado_em,resolvido_em "
                f"FROM banco.comentario WHERE {col}=%s AND user_id=%s{extra} "
                "ORDER BY criado_em ASC LIMIT 500", (alvo, user_id))
    return [{"id": _s(r[0]), "block_id": r[1], "pai_id": _s(r[2]) if r[2] else None,
             "autor_id": r[3], "corpo": r[4], "criado_em": r[5].isoformat(),
             "atualizado_em": r[6].isoformat(),
             "resolvido_em": r[7].isoformat() if r[7] else None} for r in cur.fetchall()]


def criar_comentario(cur, user_id: str, *, no_id=None, linha_id=None, block_id=None,
                     pai_id=None, corpo=""):
    if (no_id is None) == (linha_id is None):
        raise ErroDeBanco("comentário pertence a um nó OU a uma linha")
    texto = (corpo or '').strip()
    if not texto:
        raise ErroDeBanco("comentário vazio")
    if len(texto) > 20_000:
        raise ErroDeBanco("comentário acima de 20 mil caracteres")
    ident = _uid()
    cur.execute("INSERT INTO banco.comentario "
                "(id,user_id,no_id,linha_id,block_id,pai_id,autor_id,corpo) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING criado_em",
                (ident, user_id, no_id, linha_id, (block_id or None), pai_id,
                 user_id, texto))
    criado = cur.fetchone()[0]
    return {"id": _s(ident), "block_id": block_id or None, "pai_id": pai_id or None,
            "autor_id": user_id, "corpo": texto, "criado_em": criado.isoformat(),
            "atualizado_em": criado.isoformat(), "resolvido_em": None}


def resolver_comentario(cur, user_id: str, comentario_id: str, *, resolvido=True):
    cur.execute("UPDATE banco.comentario SET resolvido_em=" + ("now()" if resolvido else "NULL") +
                ",atualizado_em=now() WHERE id=%s AND user_id=%s RETURNING id,resolvido_em",
                (comentario_id, user_id))
    r = cur.fetchone()
    if not r:
        raise ErroDeBanco("comentário não encontrado")
    return {"id": _s(r[0]), "resolvido_em": r[1].isoformat() if r[1] else None}


def apagar_comentario(cur, user_id: str, comentario_id: str) -> bool:
    cur.execute("DELETE FROM banco.comentario WHERE id=%s AND user_id=%s",
                (comentario_id, user_id))
    return cur.rowcount > 0


# ── relações ──────────────────────────────────────────────────────────────────
def ligar(cur, user_id: str, propriedade_id: str, origem_id: str, destino_id: str) -> bool:
    cur.execute("INSERT INTO banco.elo (id,user_id,propriedade_id,origem_id,destino_id) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (propriedade_id,origem_id,destino_id) DO NOTHING",
                (_uid(), user_id, propriedade_id, origem_id, destino_id))
    return cur.rowcount > 0


def desligar(cur, user_id: str, propriedade_id: str, origem_id: str, destino_id: str) -> bool:
    cur.execute("DELETE FROM banco.elo WHERE user_id=%s AND propriedade_id=%s "
                "AND origem_id=%s AND destino_id=%s",
                (user_id, propriedade_id, origem_id, destino_id))
    return cur.rowcount > 0


def ligados(cur, user_id: str, linha_id: str) -> dict:
    """Os dois sentidos. Retrolink é metade do valor de uma relação, e é o que jsonb
    não dá de graça."""
    cur.execute("SELECT e.propriedade_id, l.id, l.titulo FROM banco.elo e "
                "JOIN banco.linha l ON l.id = e.destino_id "
                "WHERE e.user_id=%s AND e.origem_id=%s AND l.deletado_em IS NULL",
                (user_id, linha_id))
    saindo = [{"propriedade_id": _s(p), "id": _s(i), "titulo": t, "sentido": "saindo"} for p, i, t in cur.fetchall()]
    cur.execute("SELECT e.propriedade_id, l.id, l.titulo FROM banco.elo e "
                "JOIN banco.linha l ON l.id = e.origem_id "
                "WHERE e.user_id=%s AND e.destino_id=%s AND l.deletado_em IS NULL",
                (user_id, linha_id))
    entrando = [{"propriedade_id": _s(p), "id": _s(i), "titulo": t, "sentido": "entrando"} for p, i, t in cur.fetchall()]
    return {"saindo": saindo, "entrando": entrando}


# ── índice sob demanda ────────────────────────────────────────────────────────
def garantir_indice(cur, user_id: str, no_id: str, chave: str, tipo: str) -> Optional[str]:
    """Cria índice btree de expressão para (base, chave), com teto por base.

    NÃO usa CONCURRENTLY aqui de propósito: CONCURRENTLY não roda dentro de
    transação e pode deixar índice inválido se falhar. Quem chama roda isto fora do
    caminho de request, na criação/edição da vista, onde uma pausa de milissegundos é
    aceitável e a falha é visível."""
    if not _CHAVE_OK.match(chave or ""):
        raise ErroDeBanco(f"chave inválida: {chave!r}")
    no_id = _s(no_id)
    cur.execute("SELECT count(*) FROM pg_indexes WHERE schemaname='banco' "
                "AND indexname LIKE %s", (f"ixp_{no_id.replace('-', '')[:16]}_%",))
    if cur.fetchone()[0] >= TETO_INDICES_POR_BASE:
        return None
    curto = no_id.replace("-", "")[:16]
    nome = f"ixp_{curto}_{chave}"[:63]
    # Só numérico ganha cast: `numeric_in` é IMMUTABLE e serve em índice.
    # `timestamptz_in` é apenas STABLE e o Postgres RECUSA em expressão de índice
    # (verificado: provolatile='s'). Data é indexada como TEXTO ISO, exatamente a
    # mesma expressão que a consulta usa — se as duas divergirem, o índice existe e
    # nunca é escolhido, e ninguém entende por que a vista está lenta.
    cast = "::numeric" if tipo in ("numero", "moeda", "rollup") else ""
    if tipo == "data":
        expr = f"(NULLIF(COALESCE(props->'{chave}'->>'inicio', props->>'{chave}'),''))"
    else:
        expr = f"(NULLIF(props->>'{chave}','')" + (f"{cast})" if cast else ")")
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS {nome} ON banco.linha ({expr}) "
        f"WHERE no_id = '{no_id}'::uuid AND deletado_em IS NULL")
    return nome


def indices_invalidos(cur) -> list:
    """Um CREATE INDEX que falhou deixa índice INVALID que o planejador ignora em
    silêncio: a vista fica lenta e ninguém sabe por quê."""
    cur.execute("SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='banco' AND NOT i.indisvalid")
    return [r[0] for r in cur.fetchall()]
