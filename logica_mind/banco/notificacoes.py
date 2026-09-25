"""Inbox persistente e lembretes derivados das propriedades de data da Life."""
from __future__ import annotations

from datetime import datetime, timedelta
import os
from uuid import uuid4
from zoneinfo import ZoneInfo


ANTECEDENCIA = {
    "no_horario": timedelta(),
    "10_minutos": timedelta(minutes=10),
    "1_hora": timedelta(hours=1),
    "1_dia": timedelta(days=1),
}


def criar(cur, user_id: str, *, chave: str, tipo: str, titulo: str, corpo: str = "",
          no_id=None, linha_id=None, agente=None, disponivel_em=None):
    ident = str(uuid4())
    cur.execute("""INSERT INTO banco.notificacao
                   (id,user_id,chave,tipo,titulo,corpo,no_id,linha_id,agente,disponivel_em)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,COALESCE(%s,now()))
                   ON CONFLICT (user_id,chave) DO UPDATE SET
                     tipo=EXCLUDED.tipo,titulo=EXCLUDED.titulo,corpo=EXCLUDED.corpo,
                     no_id=EXCLUDED.no_id,linha_id=EXCLUDED.linha_id,agente=EXCLUDED.agente,
                     disponivel_em=EXCLUDED.disponivel_em
                   RETURNING id,disponivel_em""",
                (ident, user_id, chave[:300], tipo[:40], titulo[:400], corpo[:4000],
                 no_id, linha_id, agente, disponivel_em))
    r = cur.fetchone()
    return {"id": str(r[0]), "disponivel_em": r[1].isoformat()}


def sincronizar_lembretes(cur, user_id: str, linha: dict):
    """Reconstrói apenas lembretes ainda não entregues desta linha."""
    cur.execute("DELETE FROM banco.notificacao WHERE user_id=%s AND linha_id=%s "
                "AND tipo='lembrete' AND lida_em IS NULL", (user_id, linha["id"]))
    tz = ZoneInfo(os.environ.get("TZ") or "America/Fortaleza")
    criados = []
    for chave, valor in (linha.get("props") or {}).items():
        if not isinstance(valor, dict) or not valor.get("inicio") or valor.get("lembrete") not in ANTECEDENCIA:
            continue
        try:
            horario = valor.get("hora") or "09:00"
            instante = datetime.fromisoformat(f"{str(valor['inicio'])[:10]}T{horario}").replace(tzinfo=tz)
        except (TypeError, ValueError):
            continue
        instante -= ANTECEDENCIA[valor["lembrete"]]
        criados.append(criar(cur, user_id,
            chave=f"lembrete:{linha['id']}:{chave}:{valor['inicio']}:{horario}",
            tipo="lembrete", titulo=linha.get("titulo") or "Lembrete",
            corpo=f"{str(valor['inicio'])[:10]} às {horario}", no_id=linha.get("no_id"),
            linha_id=linha["id"], disponivel_em=instante))
    return criados


def listar(cur, user_id: str, *, incluir_lidas=False, incluir_futuras=False, limite=100):
    onde = ["user_id=%s"]
    params = [user_id]
    if not incluir_lidas:
        onde.append("lida_em IS NULL")
    if not incluir_futuras:
        onde.append("disponivel_em<=now()")
    params.append(max(1, min(int(limite or 100), 200)))
    cur.execute("SELECT id,chave,tipo,titulo,corpo,no_id,linha_id,agente,disponivel_em,lida_em,criado_em "
                "FROM banco.notificacao WHERE " + " AND ".join(onde) +
                " ORDER BY lida_em NULLS FIRST,disponivel_em DESC LIMIT %s", params)
    return [{"id": str(r[0]), "chave": r[1], "tipo": r[2], "titulo": r[3],
             "corpo": r[4], "no_id": str(r[5]) if r[5] else None,
             "linha_id": str(r[6]) if r[6] else None, "agente": r[7],
             "disponivel_em": r[8].isoformat(), "lida_em": r[9].isoformat() if r[9] else None,
             "criado_em": r[10].isoformat()} for r in cur.fetchall()]


def ler(cur, user_id: str, ident=None):
    if ident:
        cur.execute("UPDATE banco.notificacao SET lida_em=COALESCE(lida_em,now()) "
                    "WHERE id=%s AND user_id=%s", (ident, user_id))
    else:
        cur.execute("UPDATE banco.notificacao SET lida_em=COALESCE(lida_em,now()) "
                    "WHERE user_id=%s AND lida_em IS NULL AND disponivel_em<=now()", (user_id,))
    return cur.rowcount
