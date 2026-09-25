"""Recorrência real de registros, executada no mesmo commit da conclusão.

Não é um cron paralelo e não depende da Life estar aberta: qualquer canal, agente ou
CLI que conclua uma tarefa pela API do Mind produz a próxima ocorrência exatamente
uma vez. As chaves internas começam por `_` e nunca viram propriedades visíveis.
"""
from __future__ import annotations

from datetime import date, timedelta
import json
import unicodedata


CONCLUIDOS = {"feito", "concluido", "concluida", "entregue", "arquivado", "arquivada"}


def _texto(valor):
    if isinstance(valor, dict):
        valor = valor.get("nome") or valor.get("valor") or ""
    return str(valor or "")


def _normal(valor):
    texto = unicodedata.normalize("NFKD", _texto(valor)).encode("ascii", "ignore").decode()
    return texto.strip().lower().replace(" ", "_")


def proxima_data(inicio: str, regra: str) -> str | None:
    try:
        atual = date.fromisoformat(str(inicio)[:10])
    except (TypeError, ValueError):
        return None
    regra = _normal(regra)
    if regra in ("diaria", "diario"):
        nova = atual + timedelta(days=1)
    elif regra in ("dias_uteis", "dia_util"):
        nova = atual + timedelta(days=1)
        while nova.weekday() >= 5:
            nova += timedelta(days=1)
    elif regra in ("semanal", "semanalmente"):
        nova = atual + timedelta(days=7)
    elif regra in ("mensal", "mensalmente"):
        mes = atual.month + 1
        ano = atual.year + (mes > 12)
        mes = 1 if mes > 12 else mes
        # recua apenas o necessário para meses curtos
        dia = atual.day
        while dia:
            try:
                nova = date(ano, mes, dia)
                break
            except ValueError:
                dia -= 1
    elif regra in ("anual", "anualmente"):
        try:
            nova = atual.replace(year=atual.year + 1)
        except ValueError:  # 29 de fevereiro
            nova = atual.replace(year=atual.year + 1, day=28)
    else:
        return None
    return nova.isoformat()


def gerar_proxima(cur, user_id: str, linha: dict, nucleo):
    props = dict(linha.get("props") or {})
    if props.get("_recorrencia_proxima_id"):
        return None
    estado = _normal(props.get("estado") or props.get("status"))
    if estado not in CONCLUIDOS:
        return None

    chave_data = None
    valor_data = None
    regra = None
    for chave, valor in props.items():
        if isinstance(valor, dict) and valor.get("inicio") and valor.get("recorrencia"):
            chave_data, valor_data, regra = chave, valor, valor.get("recorrencia")
            break
    if not regra:
        regra = props.get("recorrencia")
        if _normal(regra) in ("", "nao_repetir"):
            return None
        cur.execute("SELECT chave FROM banco.propriedade WHERE user_id=%s AND no_id=%s "
                    "AND tipo='data' ORDER BY ordem", (user_id, linha["no_id"]))
        for (chave,) in cur.fetchall():
            valor = props.get(chave)
            inicio = valor.get("inicio") if isinstance(valor, dict) else valor
            if inicio and chave not in ("concluida_em", "concluido_em"):
                chave_data, valor_data = chave, valor
                break
    inicio = valor_data.get("inicio") if isinstance(valor_data, dict) else valor_data
    proxima = proxima_data(inicio, regra)
    if not (chave_data and proxima):
        return None

    clone = dict(props)
    if isinstance(valor_data, dict):
        novo_valor = dict(valor_data)
        antigo_fim = valor_data.get("fim")
        if antigo_fim:
            try:
                duracao = date.fromisoformat(str(antigo_fim)[:10]) - date.fromisoformat(str(inicio)[:10])
                novo_valor["fim"] = (date.fromisoformat(proxima) + duracao).isoformat()
            except ValueError:
                novo_valor.pop("fim", None)
        novo_valor["inicio"] = proxima
        clone[chave_data] = novo_valor
    else:
        clone[chave_data] = proxima
    clone.pop("concluida_em", None)
    clone.pop("concluido_em", None)
    clone.pop("_recorrencia_proxima_id", None)
    clone["_recorrencia_de"] = linha["id"]

    cur.execute("SELECT chave,config FROM banco.propriedade WHERE user_id=%s AND no_id=%s "
                "AND chave IN ('estado','status')", (user_id, linha["no_id"]))
    for chave, config in cur.fetchall():
        opcoes = (config or {}).get("opcoes") or []
        nomes = [_texto(o) for o in opcoes]
        inicial = next((n for n in nomes if _normal(n) not in CONCLUIDOS), None)
        clone[chave] = inicial or ("A fazer" if chave == "estado" else "Planejamento")

    criada = nucleo.criar_linha(cur, user_id, linha["no_id"], clone)
    props["_recorrencia_proxima_id"] = criada["id"]
    cur.execute("UPDATE banco.linha SET props=%s WHERE id=%s AND user_id=%s",
                (json.dumps(props), linha["id"], user_id))
    linha["props"] = props
    return criada
