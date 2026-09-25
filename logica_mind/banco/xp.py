"""Motor de progresso do Banco de dados: XP, nível, rank, atributos e sequência.

O princípio que separa isto de um jogo de fingir: **XP é subproduto de evento
registrado, calculado no servidor**. Não existe, e nunca vai existir, um endpoint
"somar XP". Quem marca a tarefa como feita é quem gera o evento. O navegador não sabe
quanto vale nada; ele recebe o saldo.

Quatro decisões que parecem detalhe e não são:

1. IDEMPOTÊNCIA POR CHAVE. `chave_idem = tipo:linha:dia_local`, com UNIQUE no banco e
   `ON CONFLICT DO NOTHING`. Sem isso, duplo clique dobra o XP, e placar sem
   integridade vira número que ninguém confia.

2. REVERSÃO. Desmarcar apaga o evento pela chave. Isto não é refinamento: sem
   reversão, marcar e desmarcar é bomba de XP infinita, e é o primeiro defeito que
   qualquer pessoa encontra POR ACIDENTE, no primeiro dia.

3. TETO DIÁRIO. Sem teto, o produto vira fazenda: criar quarenta tarefas de um segundo
   e concluir todas. Com teto, e com o aviso honesto de quanto ficou retido, o número
   volta a significar alguma coisa.

4. FUSO. A data é a LOCAL da pessoa, nunca UTC. Marcar hábito às 23h30 no Brasil é
   02h30 UTC do dia seguinte: com data UTC, a sequência quebra sozinha. É o defeito
   mais comum desta categoria de produto.

E o teste de honestidade, que é executável: `recalcular` reconstrói nível, XP e os
cinco atributos A PARTIR DOS EVENTOS e tem que dar exatamente o mesmo resultado. Número
que não se reconstrói a partir do evento foi inventado.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Optional
from zoneinfo import ZoneInfo

from .esquema import ATRIBUTOS

TETO_DIARIO = 300

# tipo de evento -> (xp, atributo, teto por dia). Tabela declarativa: acrescentar
# evento não muda código nenhum além desta linha.
TABELA = {
    "tarefa_concluida":      (10,  "ORDEM",  None),
    "tarefa_no_prazo":       (5,   "ORDEM",  None),   # bônus, some junto com a tarefa
    "mit_concluida":         (25,  "FOCO",   3),
    "habito_marcado":        (8,   None,     None),   # atributo vem do próprio hábito
    "habito_streak_7":       (4,   None,     None),
    "habito_streak_30":      (8,   None,     None),
    "diario_do_dia":         (20,  "MENTE",  1),
    "medicao_saude":         (5,   "CORPO",  3),
    "lancamento_financeiro": (3,   "ORDEM",  10),
    "leitura_progresso":     (6,   "MENTE",  1),
    "leitura_concluida":     (60,  "MENTE",  None),
    "rotina_feita":          (15,  "ORDEM",  None),
    "documento_escrito":     (5,   "MENTE",  4),
    "projeto_concluido":     (120, "ORDEM",  None),
    "meta_concluida":        (200, "VIGOR",  None),
}

FAIXAS = [(1, "INICIANDO"), (5, "CONSTANTE"), (10, "CONSOLIDADO"),
          (15, "DISCIPLINADO"), (20, "EXEMPLAR"), (30, "REFERÊNCIA")]

# Meia-vida de ~15 dias. O atributo CAI quando a pessoa para, e é justamente isso que
# o torna útil: "CORPO 31, caindo há três semanas" é informação; "CORPO 847" é ruído.
DECAIMENTO = 0.955
# calibrado para que 100 corresponda a ~40 XP/dia sustentados naquele eixo
_K = 100.0 * (1.0 - DECAIMENTO) / 40.0


class ErroDeProgresso(ValueError):
    pass


def xp_para_nivel(n: int) -> int:
    """Soma triangular: nível 2 aos 100, 3 aos 300, 10 aos 4.500, 20 aos 21.000.
    Rápido no começo, longo depois, sem teto artificial e auditável de cabeça."""
    return 100 * n * (n + 1) // 2


def nivel_de(xp_total: int) -> int:
    n = 1
    while xp_para_nivel(n) <= xp_total:
        n += 1
    return n


def rank_de(nivel: int) -> str:
    r = FAIXAS[0][1]
    for piso, nome in FAIXAS:
        if nivel >= piso:
            r = nome
    return r


def progresso_do_nivel(xp_total: int) -> dict:
    n = nivel_de(xp_total)
    piso = xp_para_nivel(n - 1) if n > 1 else 0
    teto = xp_para_nivel(n)
    return {"nivel": n, "rank": rank_de(n), "xp_total": xp_total,
            "xp_no_nivel": xp_total - piso, "xp_do_nivel": teto - piso,
            "fracao": 0.0 if teto == piso else (xp_total - piso) / (teto - piso)}


# ── perfil e data local ───────────────────────────────────────────────────────
def perfil(cur, user_id: str) -> dict:
    cur.execute("SELECT xp_total,nivel,rank,tz,modo_progresso FROM banco.perfil WHERE user_id=%s",
                (user_id,))
    r = cur.fetchone()
    if not r:
        cur.execute("INSERT INTO banco.perfil (user_id) VALUES (%s) "
                    "ON CONFLICT (user_id) DO NOTHING", (user_id,))
        cur.execute("SELECT xp_total,nivel,rank,tz,modo_progresso FROM banco.perfil WHERE user_id=%s",
                    (user_id,))
        r = cur.fetchone()
    return {"xp_total": r[0], "nivel": r[1], "rank": r[2], "tz": r[3], "modo": r[4]}


def hoje_local(tz: str) -> dt.date:
    try:
        return dt.datetime.now(ZoneInfo(tz)).date()
    except Exception:
        # fuso inválido não pode derrubar o registro do dia; cai no de casa e segue
        return dt.datetime.now(ZoneInfo("America/Sao_Paulo")).date()


def xp_do_dia(cur, user_id: str, dia: dt.date) -> int:
    cur.execute("SELECT COALESCE(SUM(xp),0) FROM banco.xp_evento "
                "WHERE user_id=%s AND dia_local=%s", (user_id, dia))
    return int(cur.fetchone()[0])


# ── registrar e reverter ──────────────────────────────────────────────────────
def registrar(cur, user_id: str, tipo: str, *, linha_id: str = None, no_id: str = None,
              atributo: str = None, dia: dt.date = None, meta: dict = None) -> dict:
    """Devolve {creditado, xp, retido, motivo}. NUNCA levanta por evento repetido:
    repetir é o caso normal (duplo clique, reenvio da rede), e é para isso que existe
    a chave de idempotência."""
    if tipo not in TABELA:
        raise ErroDeProgresso(f"tipo de evento desconhecido: {tipo}")
    import json
    base_xp, atributo_padrao, teto_tipo = TABELA[tipo]
    atributo = (atributo or atributo_padrao or "ORDEM").upper()
    if atributo not in ATRIBUTOS:
        raise ErroDeProgresso(f"atributo inválido: {atributo}")

    p = perfil(cur, user_id)
    dia = dia or hoje_local(p["tz"])
    chave = f"{tipo}:{linha_id or no_id or '-'}:{dia.isoformat()}"

    # teto por tipo, no dia
    if teto_tipo is not None:
        cur.execute("SELECT count(*) FROM banco.xp_evento "
                    "WHERE user_id=%s AND dia_local=%s AND tipo=%s", (user_id, dia, tipo))
        if cur.fetchone()[0] >= teto_tipo:
            return {"creditado": False, "xp": 0, "retido": base_xp,
                    "motivo": f"teto de {teto_tipo} por dia para {tipo}"}

    # teto global do dia. O que passa é RETIDO e dito em voz alta: silêncio aqui faz
    # a pessoa achar que o placar quebrou.
    ja = xp_do_dia(cur, user_id, dia)
    if ja >= TETO_DIARIO:
        return {"creditado": False, "xp": 0, "retido": base_xp,
                "motivo": f"teto diário de {TETO_DIARIO} XP atingido"}
    xp = min(base_xp, TETO_DIARIO - ja)
    retido = base_xp - xp

    cur.execute(
        "INSERT INTO banco.xp_evento (user_id,dia_local,tipo,atributo,xp,no_id,linha_id,chave_idem,meta) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (chave_idem) DO NOTHING RETURNING id",
        (user_id, dia, tipo, atributo, xp, no_id, linha_id, chave, json.dumps(meta or {})))
    r = cur.fetchone()
    if not r:
        return {"creditado": False, "xp": 0, "retido": 0, "motivo": "já registrado hoje"}

    _aplicar_saldo(cur, user_id, atributo, xp)
    return {"creditado": True, "xp": xp, "retido": retido,
            "motivo": None if not retido else f"{retido} XP retidos pelo teto do dia"}


def reverter(cur, user_id: str, tipo: str, *, linha_id: str = None, no_id: str = None,
             dia: dt.date = None) -> bool:
    """Desmarcar devolve o XP. Sem isto, marcar e desmarcar é bomba de XP infinita."""
    p = perfil(cur, user_id)
    dia = dia or hoje_local(p["tz"])
    chave = f"{tipo}:{linha_id or no_id or '-'}:{dia.isoformat()}"
    cur.execute("DELETE FROM banco.xp_evento WHERE user_id=%s AND chave_idem=%s "
                "RETURNING atributo, xp", (user_id, chave))
    r = cur.fetchone()
    if not r:
        return False
    _aplicar_saldo(cur, user_id, r[0], -int(r[1]))
    return True


def _aplicar_saldo(cur, user_id: str, atributo: str, delta: int) -> None:
    cur.execute(
        "INSERT INTO banco.atributo_saldo (user_id,atributo,xp) VALUES (%s,%s,%s) "
        "ON CONFLICT (user_id,atributo) DO UPDATE SET xp = banco.atributo_saldo.xp + %s, "
        "atualizado_em = now()", (user_id, atributo, delta, delta))
    cur.execute(
        "INSERT INTO banco.perfil (user_id, xp_total) VALUES (%s,%s) "
        "ON CONFLICT (user_id) DO UPDATE SET xp_total = GREATEST(0, banco.perfil.xp_total + %s), "
        "atualizado_em = now() RETURNING xp_total", (user_id, max(0, delta), delta))
    total = int(cur.fetchone()[0])
    n = nivel_de(total)
    cur.execute("UPDATE banco.perfil SET nivel=%s, rank=%s WHERE user_id=%s",
                (n, rank_de(n), user_id))


# ── atributos derivados ───────────────────────────────────────────────────────
def recalcular_atributos(cur, user_id: str, ate: dt.date = None) -> dict:
    """Reconstrói os cinco atributos A PARTIR DOS EVENTOS, do zero.

    É o teste de honestidade do produto e ele é executável: se um número não puder ser
    reconstruído a partir dos eventos, ele foi inventado. Roda também como job diário,
    porque a média móvel precisa DECAIR nos dias sem evento, e dia sem evento não gera
    escrita nenhuma."""
    p = perfil(cur, user_id)
    ate = ate or hoje_local(p["tz"])
    cur.execute("SELECT dia_local, atributo, SUM(xp) FROM banco.xp_evento "
                "WHERE user_id=%s AND dia_local <= %s GROUP BY 1,2 ORDER BY 1",
                (user_id, ate))
    por_dia: dict = {}
    for dia, atributo, soma in cur.fetchall():
        por_dia.setdefault(dia, {})[atributo] = int(soma)
    if not por_dia:
        valores = {a: 0.0 for a in ATRIBUTOS}
    else:
        valores = {a: 0.0 for a in ATRIBUTOS}
        dia = min(por_dia)
        while dia <= ate:
            ganhos = por_dia.get(dia, {})
            for a in ATRIBUTOS:
                valores[a] = valores[a] * DECAIMENTO + ganhos.get(a, 0) * _K * 100.0 / 100.0
            dia += dt.timedelta(days=1)
    for a in ATRIBUTOS:
        v = round(min(100.0, max(0.0, valores[a])), 2)
        cur.execute("INSERT INTO banco.atributo_saldo (user_id,atributo,valor) VALUES (%s,%s,%s) "
                    "ON CONFLICT (user_id,atributo) DO UPDATE SET valor=%s, atualizado_em=now()",
                    (user_id, a, v, v))
        valores[a] = v
    return valores


def atributos(cur, user_id: str) -> dict:
    cur.execute("SELECT atributo, xp, valor FROM banco.atributo_saldo WHERE user_id=%s",
                (user_id,))
    d = {a: {"xp": 0, "valor": 0.0} for a in ATRIBUTOS}
    for a, xp, v in cur.fetchall():
        if a in d:
            d[a] = {"xp": int(xp), "valor": float(v)}
    return d


# ── sequência ─────────────────────────────────────────────────────────────────
def marcar_sequencia(cur, user_id: str, chave: str, dia: dt.date = None,
                     janela_semanal: int = 0) -> dict:
    """Sequência com salvo-conduto e pausa.

    `janela_semanal > 0` significa cadência do tipo "3x por semana": a conta é por
    SEMANA, não por dia. Errar isso é o defeito clássico — o app zera a sequência de
    quem cumpriu a meta, e a pessoa abandona o produto com razão.

    Salvo-conduto: 1 por mês, acumula até 2. Uma gripe de dois dias não pode apagar
    noventa. Sequência que pune doença é desenho hostil, e o efeito é o abandono."""
    p = perfil(cur, user_id)
    dia = dia or hoje_local(p["tz"])
    cur.execute("SELECT atual,recorde,ultima_data,salvo_conduto,pausado_ate FROM banco.sequencia "
                "WHERE user_id=%s AND chave=%s", (user_id, chave))
    r = cur.fetchone()
    if not r:
        cur.execute("INSERT INTO banco.sequencia (user_id,chave,atual,recorde,ultima_data) "
                    "VALUES (%s,%s,1,1,%s)", (user_id, chave, dia))
        return {"atual": 1, "recorde": 1, "novo_recorde": True, "usou_salvo_conduto": False}
    atual, recorde, ultima, salvos, pausado_ate = r
    if ultima == dia:
        return {"atual": atual, "recorde": recorde, "novo_recorde": False, "usou_salvo_conduto": False}
    if pausado_ate and dia <= pausado_ate:
        novo = atual                      # pausa suspende, não zera
    elif ultima is None:
        novo = 1
    else:
        vao = (dia - ultima).days
        if janela_semanal:
            # semanas ISO consecutivas contam; dentro da mesma semana não avança
            sem_a = ultima.isocalendar()[:2]
            sem_b = dia.isocalendar()[:2]
            if sem_a == sem_b:
                novo = atual
            else:
                dif = (dia - ultima).days
                novo = atual + 1 if dif <= 14 else 1
        elif vao == 1:
            novo = atual + 1
        elif vao == 2 and salvos > 0:
            novo = atual + 1
            salvos -= 1
        else:
            novo = 1
    usou = salvos < r[3]
    recorde_novo = max(novo, recorde)
    cur.execute("UPDATE banco.sequencia SET atual=%s, recorde=%s, ultima_data=%s, "
                "salvo_conduto=%s, atualizado_em=now() WHERE user_id=%s AND chave=%s",
                (novo, recorde_novo, dia, salvos, user_id, chave))
    return {"atual": novo, "recorde": recorde_novo,
            "novo_recorde": novo > recorde, "usou_salvo_conduto": usou}


def repor_salvo_conduto(cur, user_id: str) -> int:
    """Job mensal: 1 por mês, teto de 2."""
    cur.execute("UPDATE banco.sequencia SET salvo_conduto = LEAST(2, salvo_conduto + 1) "
                "WHERE user_id=%s", (user_id,))
    return cur.rowcount


def sequencias(cur, user_id: str) -> list:
    cur.execute("SELECT chave,atual,recorde,ultima_data,salvo_conduto,pausado_ate "
                "FROM banco.sequencia WHERE user_id=%s ORDER BY atual DESC", (user_id,))
    return [{"chave": c, "atual": a, "recorde": r,
             "ultima_data": u.isoformat() if u else None,
             "salvo_conduto": s, "pausado_ate": pa.isoformat() if pa else None}
            for c, a, r, u, s, pa in cur.fetchall()]


# ── conquistas ────────────────────────────────────────────────────────────────
CONQUISTAS = [
    ("primeiro_passo",  "Primeiro passo",   "a primeira coisa registrada",            "bronze"),
    ("sequencia_7",     "Sete dias",        "sete dias seguidos num hábito",          "bronze"),
    ("sequencia_30",    "Trinta dias",      "trinta dias seguidos num hábito",        "prata"),
    ("sequencia_100",   "Cem dias",         "cem dias seguidos num hábito",           "ouro"),
    ("foco_total",      "Dia fechado",      "os três focos do dia concluídos",        "bronze"),
    ("foco_semana",     "Semana fechada",   "sete dias seguidos com o foco fechado",  "prata"),
    ("projeto_1",       "Primeiro projeto", "um projeto levado até o fim",            "bronze"),
    ("projeto_10",      "Dez projetos",     "dez projetos concluídos",                "ouro"),
    ("meta_1",          "Meta batida",      "uma meta de longo prazo concluída",      "prata"),
    ("diario_30",       "Mês escrito",      "trinta entradas de diário",              "prata"),
    ("nivel_10",        "Nível dez",        "chegou ao nível dez",                    "prata"),
    ("nivel_25",        "Nível vinte e cinco", "chegou ao nível vinte e cinco",       "ouro"),
    ("ano_ativo",       "Um ano",           "trezentos e sessenta e cinco dias ativos", "platina"),
]


def semear_conquistas(cur) -> int:
    """As definições são do produto, não do usuário. Semeadas no boot para que o slug
    desconhecido seja de fato excepcional, e não o caso comum."""
    n = 0
    for slug, nome, desc, tier in CONQUISTAS:
        cur.execute("INSERT INTO banco.conquista (slug,nome,descricao,tier) "
                    "VALUES (%s,%s,%s,%s) ON CONFLICT (slug) DO UPDATE SET "
                    "nome=excluded.nome, descricao=excluded.descricao, tier=excluded.tier",
                    (slug, nome, desc, tier))
        n += 1
    return n


def talvez_conceder(cur, user_id: str, slug: str) -> bool:
    """Idempotente por construção, no mesmo padrão do voyspark.

    O PONTO DE SALVAMENTO existe porque conceder conquista é efeito colateral de um
    evento de vida: um slug errado não pode derrubar o pedido que marcou o hábito. Sem
    o savepoint, a violação de chave estrangeira abortaria a transação inteira de quem
    chamou. E o aviso vai para o log em vez de sumir: conquista que nunca aparece por
    erro de digitação é o tipo de defeito que ninguém acha."""
    import sys as _sys
    # Em autocommit não existe transação aberta e SAVEPOINT é recusado; a instrução
    # que falha morre sozinha e a conexão segue utilizável. Dentro de transação, o
    # savepoint é o que impede a falha de abortar tudo que veio antes.
    em_transacao = not getattr(cur.connection, "autocommit", True)
    if em_transacao:
        cur.execute("SAVEPOINT sp_conquista")
    try:
        cur.execute("INSERT INTO banco.conquista_do_usuario (user_id,slug) VALUES (%s,%s) "
                    "ON CONFLICT (user_id,slug) DO NOTHING RETURNING id", (user_id, slug))
        r = cur.fetchone()
        if em_transacao:
            cur.execute("RELEASE SAVEPOINT sp_conquista")
        return r is not None
    except Exception as e:
        if em_transacao:
            cur.execute("ROLLBACK TO SAVEPOINT sp_conquista")
        print(f"[banco] conquista desconhecida {slug!r}: {e}", file=_sys.stderr)
        return False


def painel(cur, user_id: str) -> dict:
    """O que a tela de progresso mostra, num pedido só."""
    p = perfil(cur, user_id)
    dados = progresso_do_nivel(p["xp_total"])
    dados["modo"] = p["modo"]
    dados["atributos"] = atributos(cur, user_id)
    dados["sequencias"] = sequencias(cur, user_id)
    dados["xp_hoje"] = xp_do_dia(cur, user_id, hoje_local(p["tz"]))
    dados["teto_diario"] = TETO_DIARIO
    cur.execute("SELECT c.slug,c.nome,c.descricao,c.tier,u.ganha_em FROM banco.conquista c "
                "LEFT JOIN banco.conquista_do_usuario u ON u.slug=c.slug AND u.user_id=%s "
                "ORDER BY CASE c.tier WHEN 'bronze' THEN 1 WHEN 'prata' THEN 2 "
                "WHEN 'ouro' THEN 3 ELSE 4 END, c.slug", (user_id,))
    dados["conquistas"] = [{"slug": s, "nome": n, "descricao": d, "tier": t,
                            "ganha_em": g.isoformat() if g else None}
                           for s, n, d, t, g in cur.fetchall()]
    return dados
