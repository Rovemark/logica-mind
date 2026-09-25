"""Semântica operacional das relações marcadas como dependência.

Uma relação comum apenas conecta registros. Uma dependência é uma regra: o item de
origem espera o destino, não pode ser concluído antes dele e começa depois do fim
dele. A regra mora no Mind para valer igualmente no Life, Cortex, CLI e automações.
"""
from __future__ import annotations

from datetime import date, timedelta
import json
import re

from .nucleo import ErroDeBanco

_FEITO = re.compile(r"feito|conclu|entregue|finaliz|arquivado", re.I)
_STATUS = {"estado", "status"}
_IGNORAR_DATA = re.compile(r"conclu|foco|criad|atualiz|lembrete", re.I)


def _texto(valor) -> str:
    if isinstance(valor, dict):
        return str(valor.get("nome") or "")
    return "" if valor is None else str(valor)


def esta_concluido(props: dict) -> bool:
    valores = [_texto(valor) for chave, valor in (props or {}).items()
               if re.search(r"estado|status", str(chave), re.I)]
    return bool(valores) and any(_FEITO.search(valor) for valor in valores)


def _dia(valor):
    bruto = valor.get("inicio") if isinstance(valor, dict) else valor
    if not bruto:
        return None
    try:
        return date.fromisoformat(str(bruto)[:10])
    except (TypeError, ValueError):
        return None


def _fim(valor):
    bruto = valor.get("fim") if isinstance(valor, dict) else None
    if bruto:
        try:
            return date.fromisoformat(str(bruto)[:10])
        except (TypeError, ValueError):
            pass
    return _dia(valor)


def _iso_com_mesmo_sufixo(valor, novo: date):
    """Move a data sem apagar hora/fuso que um cliente tenha gravado na string."""
    if not valor:
        return novo.isoformat()
    texto = str(valor)
    return novo.isoformat() + texto[10:] if len(texto) > 10 else novo.isoformat()


def _mudou_para_concluido(cur, user_id: str, linha_id: str, mudancas: dict) -> bool:
    candidatas = [k for k, v in (mudancas or {}).items() if _FEITO.search(_texto(v))]
    if not candidatas:
        return False
    cur.execute("SELECT p.chave,p.nome FROM banco.linha l JOIN banco.propriedade p "
                "ON p.no_id=l.no_id AND p.user_id=l.user_id "
                "WHERE l.id=%s AND l.user_id=%s AND p.chave=ANY(%s)",
                (linha_id, user_id, candidatas))
    return any(chave in _STATUS or re.search(r"estado|status", f"{chave} {nome}", re.I)
               for chave, nome in cur.fetchall())


def bloqueios_pendentes(cur, user_id: str, linha_id: str) -> list[dict]:
    """Retorna os destinos ainda não concluídos de relações de dependência."""
    cur.execute("SELECT l.id,l.titulo,l.props,l.no_id FROM banco.elo e "
                "JOIN banco.propriedade r ON r.id=e.propriedade_id AND r.user_id=e.user_id "
                "JOIN banco.linha l ON l.id=e.destino_id AND l.user_id=e.user_id "
                "WHERE e.user_id=%s AND e.origem_id=%s AND l.deletado_em IS NULL "
                "AND r.config->>'semantica'='dependencia'", (user_id, linha_id))
    alvos = cur.fetchall()
    if not alvos:
        return []
    nos = list({str(r[3]) for r in alvos})
    cur.execute("SELECT no_id,chave FROM banco.propriedade WHERE user_id=%s "
                "AND no_id=ANY(%s::uuid[]) AND (chave IN ('estado','status') "
                "OR lower(nome) ~ '(estado|status)' OR chave ~ '(estado|status)')", (user_id, nos))
    chaves = {}
    for no_id, chave in cur.fetchall():
        chaves.setdefault(str(no_id), []).append(chave)
    pendentes = []
    for ident, titulo, props, no_id in alvos:
        valores = [_texto((props or {}).get(k)) for k in chaves.get(str(no_id), [])]
        if not valores or not any(_FEITO.search(v) for v in valores):
            pendentes.append({"id": str(ident), "titulo": titulo or "Sem título"})
    return pendentes


def validar_conclusao(cur, user_id: str, linha_id: str, mudancas: dict) -> None:
    if not _mudou_para_concluido(cur, user_id, linha_id, mudancas):
        return
    pendentes = bloqueios_pendentes(cur, user_id, linha_id)
    if pendentes:
        nomes = ", ".join(p["titulo"] for p in pendentes[:3])
        resto = f" e mais {len(pendentes) - 3}" if len(pendentes) > 3 else ""
        raise ErroDeBanco(f"Este item está bloqueado por: {nomes}{resto}. Conclua as dependências primeiro.")


def _campos_data(cur, user_id: str, no_id: str):
    cur.execute("SELECT chave,nome FROM banco.propriedade WHERE user_id=%s AND no_id=%s "
                "AND tipo='data' ORDER BY ordem", (user_id, no_id))
    campos = [(chave, nome or chave) for chave, nome in cur.fetchall()
              if not _IGNORAR_DATA.search(f"{chave} {nome}")]
    def prioridade(item):
        texto = f"{item[0]} {item[1]}".lower()
        if re.search(r"in[ií]cio|come[cç]", texto): return 0
        if re.search(r"prazo|quando|data", texto): return 1
        if re.search(r"fim|t[eé]rmino", texto): return 2
        return 3
    return sorted(campos, key=prioridade)


def _limites(props: dict, campos):
    existentes = [(chave, nome, props.get(chave)) for chave, nome in campos if _dia(props.get(chave))]
    if not existentes:
        return None
    inicio = next((x for x in existentes if re.search(r"in[ií]cio|come[cç]", f"{x[0]} {x[1]}", re.I)), existentes[0])
    fim_separado = next((x for x in existentes if re.search(r"fim|t[eé]rmino", f"{x[0]} {x[1]}", re.I)), None)
    termina = _fim(fim_separado[2]) if fim_separado else _fim(inicio[2])
    return {"chave": inicio[0], "valor": inicio[2], "inicio": _dia(inicio[2]),
            "fim": termina or _dia(inicio[2]), "fim_separado": fim_separado}


def _mover_props(props: dict, limites: dict, novo_inicio: date) -> dict:
    novos = dict(props or {})
    delta = novo_inicio - limites["inicio"]
    valor = limites["valor"]
    if isinstance(valor, dict):
        movido = dict(valor)
        movido["inicio"] = _iso_com_mesmo_sufixo(valor.get("inicio"), novo_inicio)
        if valor.get("fim"):
            movido["fim"] = _iso_com_mesmo_sufixo(valor.get("fim"), _fim(valor) + delta)
        novos[limites["chave"]] = movido
    else:
        novos[limites["chave"]] = _iso_com_mesmo_sufixo(valor, novo_inicio)
    separado = limites.get("fim_separado")
    if separado and separado[0] != limites["chave"]:
        valor_fim = separado[2]
        novo_fim = _fim(valor_fim) + delta
        if isinstance(valor_fim, dict):
            objeto = dict(valor_fim); objeto["inicio"] = _iso_com_mesmo_sufixo(valor_fim.get("inicio"), novo_fim)
            if valor_fim.get("fim"): objeto["fim"] = _iso_com_mesmo_sufixo(valor_fim.get("fim"), _fim(valor_fim) + delta)
            novos[separado[0]] = objeto
        else:
            novos[separado[0]] = _iso_com_mesmo_sufixo(valor_fim, novo_fim)
    return novos


def _carregar_linha(cur, user_id: str, linha_id: str):
    cur.execute("SELECT id,no_id,titulo,props FROM banco.linha WHERE id=%s AND user_id=%s "
                "AND deletado_em IS NULL", (linha_id, user_id))
    r = cur.fetchone()
    return None if not r else {"id": str(r[0]), "no_id": str(r[1]), "titulo": r[2], "props": dict(r[3] or {})}


def reprogramar_par(cur, user_id: str, dependente_id: str, dependencia_id: str):
    """Garante que o dependente comece no dia seguinte ao fim da dependência."""
    dependente = _carregar_linha(cur, user_id, dependente_id)
    dependencia = _carregar_linha(cur, user_id, dependencia_id)
    if not dependente or not dependencia:
        return None
    lim_dep = _limites(dependencia["props"], _campos_data(cur, user_id, dependencia["no_id"]))
    lim_item = _limites(dependente["props"], _campos_data(cur, user_id, dependente["no_id"]))
    if not lim_dep or not lim_item or lim_item["inicio"] > lim_dep["fim"]:
        return None
    novo_inicio = lim_dep["fim"] + timedelta(days=1)
    novos = _mover_props(dependente["props"], lim_item, novo_inicio)
    cur.execute("UPDATE banco.linha SET props=%s::jsonb,atualizado_em=now() "
                "WHERE id=%s AND user_id=%s", (json.dumps(novos), dependente_id, user_id))
    return {**dependente, "props": novos, "novo_inicio": novo_inicio.isoformat(),
            "causa": dependencia["titulo"] or "dependência"}


def reprogramar_elo(cur, user_id: str, propriedade_id: str, dependente_id: str, dependencia_id: str):
    cur.execute("SELECT 1 FROM banco.propriedade WHERE id=%s AND user_id=%s "
                "AND config->>'semantica'='dependencia'", (propriedade_id, user_id))
    return reprogramar_par(cur, user_id, dependente_id, dependencia_id) if cur.fetchone() else None


def reprogramar_dependentes(cur, user_id: str, linha_id: str, notificar=None) -> list[dict]:
    """Propaga ajustes por toda a cadeia, com teto e proteção contra ciclos."""
    fila = [linha_id]
    vistos = set()
    alterados = []
    while fila and len(vistos) < 100:
        dependencia_id = fila.pop(0)
        if dependencia_id in vistos:
            continue
        vistos.add(dependencia_id)
        cur.execute("SELECT e.origem_id FROM banco.elo e JOIN banco.propriedade p "
                    "ON p.id=e.propriedade_id AND p.user_id=e.user_id "
                    "WHERE e.user_id=%s AND e.destino_id=%s "
                    "AND p.config->>'semantica'='dependencia'", (user_id, dependencia_id))
        for (dependente_id,) in cur.fetchall():
            mudanca = reprogramar_par(cur, user_id, str(dependente_id), dependencia_id)
            if mudanca:
                alterados.append(mudanca); fila.append(str(dependente_id))
                if notificar:
                    notificar(mudanca)
    return alterados
