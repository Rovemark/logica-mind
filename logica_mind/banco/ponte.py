"""A ponte do Banco de dados para a Memória. É o que nenhum Notion tem.

O Banco de dados guarda o que É. A Memória guarda o que SIGNIFICA. A ponte é o que faz
fechar trinta dias de treino virar a frase "manteve o treino trinta dias seguidos" na
memória do Astro, sem que a lista de compras vire memória junto.

Três decisões que essa ponte só funciona por causa delas:

1. CAIXA DE SAÍDA, NUNCA SÍNCRONO. O handler HTTP não pode chamar `mind.remember()`
   dentro da requisição: o extrator roda a CLI `claude` e leva SEGUNDOS segurando um
   dos 32 workers. Seria o colapso de 2026 entrando pela porta da frente. A mutação
   grava em `evento_pendente` na mesma transação; UMA thread daemon, fora do pool
   HTTP, drena depois.

2. NAMESPACE `vida`, NUNCA `astro`. Nenhum dos 57 agentes consulta `vida` por padrão.
   É o isolamento que impede a lista de compras de sujar o recall de todo mundo, e
   custa zero código: é só o namespace.

3. `log()` PARA REPETÍVEL, `remember()` PARA RARO. O `remember()` deduplica a 0.92
   (`core.py:130`) e extrai fatos com LLM; o `log()` (`core.py:378`) é episódico cru,
   *sem extração e sem dedup*. Hábito marcado todo dia É repetição legítima: vai de
   `log()`, e o problema do dedup some por construção, sem gambiarra de variar o texto
   para escapar do limiar (que funciona por acidente e quebra quando o embedder mudar).

O Life é também uma fonte de memória do dono. O estado atual de páginas, bases e
linhas é indexado semanticamente no namespace ``vida``. A unidade é o RECURSO,
não o clique: salvar de novo substitui os fragmentos anteriores do mesmo recurso,
e apagar/lixeira remove todos eles. Assim o sistema lembra o que está no Life sem
guardar uma pilha de versões falsas a cada tecla.

Eventos de progresso continuam seletivos:

    marcar hábito hoje ................. não. Vira linha e XP.
    fechar 7 / 30 / 100 dias ........... sim, e carrega a data
    concluir projeto ................... sim, com nome e duração
    concluir meta ...................... sim
    concluir leitura ................... sim
    abandonar hábito por 14 dias ....... sim. É sinal, e o Astro precisa saber.
    escrever no diário ................. sim, resumido
    item/linha/página atual ............. sim, como estado substituível
    edição de esquema ................... sim, no retrato atual da base
    apagar ou mandar à lixeira .......... remove a memória derivada
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time

NAMESPACE = os.environ.get("LM_VIDA_NAMESPACE", "vida")

# tipo do evento -> (vira memória?, usa remember (senão log), importância)
REGRAS = {
    "vida_snapshot":        (True,  False, 0.45),
    "vida_remover":         (True,  False, 0.0),
    "habito_marcado":        (False, False, 0.0),
    "habito_streak_7":       (True,  False, 0.3),
    "habito_streak_30":      (True,  True,  0.6),
    "habito_streak_100":     (True,  True,  0.8),
    "habito_abandonado":     (True,  True,  0.6),
    "sequencia_quebrada":    (True,  False, 0.4),
    "projeto_concluido":     (True,  True,  0.7),
    "meta_concluida":        (True,  True,  0.8),
    "leitura_concluida":     (True,  True,  0.5),
    "diario_do_dia":         (True,  True,  0.5),
    "nivel_subiu":           (True,  False, 0.4),
    "tarefa_concluida":      (False, False, 0.0),
    "mit_concluida":         (False, False, 0.0),
    "medicao_saude":         (False, False, 0.0),
    "lancamento_financeiro": (False, False, 0.0),
    "rotina_feita":          (False, False, 0.0),
    "documento_escrito":     (False, False, 0.0),
    "leitura_progresso":     (False, False, 0.0),
}

_ORIGEM = "logica-life"
_TAMANHO_FRAGMENTO = max(400, int(os.environ.get("LM_VIDA_FRAGMENTO_CHARS", "1200") or 1200))
_MAX_FRAGMENTOS = max(8, int(os.environ.get("LM_VIDA_MAX_FRAGMENTOS", "96") or 96))


def ligada() -> bool:
    return os.environ.get("LM_VIDA_PONTE", "1").lower() not in ("0", "false", "no", "off")


def enfileirar(cur, user_id: str, tipo: str, payload: dict) -> bool:
    """Grava na caixa de saída, na MESMA transação da mutação. Se a mutação voltar
    atrás, o evento volta junto: memória de coisa que não aconteceu é pior que
    memória faltando."""
    if not ligada():
        return False
    vira, _, _ = REGRAS.get(tipo, (False, False, 0.0))
    if not vira:
        return False
    payload = payload or {}
    # Coalesce de autosave. Enquanto o daemon ainda não consumiu a versão anterior,
    # só a versão mais nova interessa. Sem isto, digitar durante um minuto criaria
    # dezenas de embeddings obsoletos mesmo que todos fossem apagados depois.
    recurso = payload.get("recurso")
    if tipo in ("vida_snapshot", "vida_remover") and recurso:
        cur.execute(
            "DELETE FROM banco.evento_pendente WHERE user_id=%s "
            "AND processado_em IS NULL AND tipo IN ('vida_snapshot','vida_remover') "
            "AND payload->>'recurso'=%s",
            (user_id, str(recurso)),
        )
    cur.execute("INSERT INTO banco.evento_pendente (user_id,tipo,payload) VALUES (%s,%s,%s)",
                (user_id, tipo, json.dumps(payload)))
    return True


def _texto_valor(valor) -> str:
    if valor is None or valor == "":
        return ""
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    if isinstance(valor, list):
        return ", ".join(x for x in (_texto_valor(v) for v in valor) if x)
    if isinstance(valor, dict):
        for chave in ("nome", "titulo", "label", "name"):
            if valor.get(chave):
                return str(valor[chave])
        return json.dumps(valor, ensure_ascii=False, sort_keys=True, default=str)
    return str(valor)


def _comentarios(cur, user_id: str, *, no_id=None, linha_id=None) -> list[str]:
    coluna, alvo = ("no_id", no_id) if no_id else ("linha_id", linha_id)
    if not alvo:
        return []
    cur.execute(
        f"SELECT corpo FROM banco.comentario WHERE user_id=%s AND {coluna}=%s "
        "AND resolvido_em IS NULL ORDER BY criado_em LIMIT 200",
        (user_id, alvo),
    )
    return [str(r[0]).strip() for r in cur.fetchall() if r and str(r[0]).strip()]


def _ancestrais(cur, user_id: str, no_id: str) -> tuple[list[str], list[str], bool]:
    cur.execute(
        "WITH RECURSIVE caminho AS ("
        " SELECT id,pai_id,arquivado_em FROM banco.no WHERE id=%s AND user_id=%s"
        " UNION ALL"
        " SELECT p.id,p.pai_id,p.arquivado_em FROM banco.no p"
        " JOIN caminho c ON p.id=c.pai_id WHERE p.user_id=%s"
        ") SELECT c.id,c.arquivado_em,n.nome FROM caminho c "
        "JOIN banco.no n ON n.id=c.id AND n.user_id=%s",
        (no_id, user_id, user_id, user_id),
    )
    caminho = cur.fetchall()
    return ([str(i) for i, _, _ in caminho[1:]],
            [str(nome) for _, _, nome in reversed(caminho[1:])],
            bool(caminho) and not any(a for _, a, _ in caminho))


def snapshot_no(cur, user_id: str, no_id: str) -> dict | None:
    """Materializa o estado semântico atual de uma página/base."""
    cur.execute(
        "SELECT n.id,n.tipo,n.nome,n.modelo,e.nome "
        "FROM banco.no n JOIN banco.espaco e ON e.id=n.espaco_id AND e.user_id=n.user_id "
        "WHERE n.id=%s AND n.user_id=%s AND n.arquivado_em IS NULL",
        (no_id, user_id),
    )
    r = cur.fetchone()
    if not r:
        return None
    ident, tipo, nome, modelo, espaco = r
    ancestrais, caminho, ativo = _ancestrais(cur, user_id, str(ident))
    if not ativo:
        return None
    linhas = [
        f"{('Página' if tipo == 'pagina' else 'Base de dados')} do Logica Life: {nome}.",
        f"Área: {espaco}.",
    ]
    if modelo:
        linhas.append(f"Tipo: {modelo}.")
    if caminho:
        linhas.append("Dentro de: " + " > ".join(caminho) + ".")
    if tipo == "pagina":
        cur.execute("SELECT texto FROM banco.documento WHERE no_id=%s AND user_id=%s", (ident, user_id))
        doc = cur.fetchone()
        if doc and str(doc[0] or "").strip():
            linhas.extend(("Conteúdo:", str(doc[0]).strip()))
    else:
        cur.execute(
            "SELECT nome,tipo FROM banco.propriedade WHERE no_id=%s AND user_id=%s "
            "AND oculta=false ORDER BY ordem,chave",
            (ident, user_id),
        )
        propriedades = [f"{n} ({t})" for n, t in cur.fetchall()]
        if propriedades:
            linhas.append("Propriedades: " + ", ".join(propriedades) + ".")
    comentarios = _comentarios(cur, user_id, no_id=ident)
    if comentarios:
        linhas.extend(("Comentários abertos:", "\n".join(f"- {c}" for c in comentarios)))
    return {
        "recurso": f"no:{ident}", "recurso_tipo": "pagina" if tipo == "pagina" else "base",
        "recurso_id": str(ident), "no_id": str(ident), "titulo": str(nome),
        "modelo": str(modelo or ""), "ancestrais": ancestrais,
        "texto": "\n".join(linhas).strip(),
    }


def snapshot_linha(cur, user_id: str, linha_id: str) -> dict | None:
    """Materializa uma tarefa/projeto/hábito/linha usando os rótulos visíveis."""
    cur.execute(
        "SELECT l.id,l.no_id,l.titulo,l.props,n.nome,n.modelo "
        "FROM banco.linha l JOIN banco.no n ON n.id=l.no_id AND n.user_id=l.user_id "
        "WHERE l.id=%s AND l.user_id=%s AND l.deletado_em IS NULL "
        "AND l.arquivado_em IS NULL AND n.arquivado_em IS NULL",
        (linha_id, user_id),
    )
    r = cur.fetchone()
    if not r:
        return None
    ident, no_id, titulo, props, base, modelo = r
    ancestrais, caminho, ativo = _ancestrais(cur, user_id, str(no_id))
    if not ativo:
        return None
    cur.execute(
        "SELECT chave,nome FROM banco.propriedade WHERE no_id=%s AND user_id=%s "
        "ORDER BY ordem,chave",
        (no_id, user_id),
    )
    rotulos = {str(chave): str(nome) for chave, nome in cur.fetchall()}
    linhas = [f"Item do Logica Life: {titulo or 'Sem título'}.", f"Base: {base}."]
    if modelo:
        linhas.append(f"Tipo: {modelo}.")
    if caminho:
        linhas.append("Dentro de: " + " > ".join(caminho) + ".")
    for chave, valor in (props or {}).items():
        texto = _texto_valor(valor).strip()
        if texto:
            linhas.append(f"{rotulos.get(str(chave), str(chave))}: {texto}.")
    cur.execute(
        "SELECT p.nome,d.titulo FROM banco.elo e "
        "JOIN banco.propriedade p ON p.id=e.propriedade_id AND p.user_id=e.user_id "
        "JOIN banco.linha d ON d.id=e.destino_id AND d.user_id=e.user_id "
        "WHERE e.origem_id=%s AND e.user_id=%s AND d.deletado_em IS NULL "
        "ORDER BY p.nome,d.titulo LIMIT 500",
        (ident, user_id),
    )
    relacoes = {}
    for nome_prop, titulo_destino in cur.fetchall():
        relacoes.setdefault(str(nome_prop), []).append(str(titulo_destino or "Sem título"))
    for nome_prop, destinos in relacoes.items():
        linhas.append(f"{nome_prop}: {', '.join(destinos)}.")
    cur.execute("SELECT texto FROM banco.documento WHERE linha_id=%s AND user_id=%s", (ident, user_id))
    doc = cur.fetchone()
    if doc and str(doc[0] or "").strip():
        linhas.extend(("Conteúdo:", str(doc[0]).strip()))
    comentarios = _comentarios(cur, user_id, linha_id=ident)
    if comentarios:
        linhas.extend(("Comentários abertos:", "\n".join(f"- {c}" for c in comentarios)))
    return {
        "recurso": f"linha:{ident}", "recurso_tipo": "linha", "recurso_id": str(ident),
        "no_id": str(no_id), "linha_id": str(ident), "titulo": str(titulo or "Sem título"),
        "modelo": str(modelo or ""), "ancestrais": ancestrais,
        "texto": "\n".join(linhas).strip(),
    }


def enfileirar_no(cur, user_id: str, no_id: str) -> bool:
    p = snapshot_no(cur, user_id, no_id)
    return enfileirar(cur, user_id, "vida_snapshot", p) if p else enfileirar_remocao(
        cur, user_id, recurso=f"no:{no_id}", no_id=no_id)


def enfileirar_linha(cur, user_id: str, linha_id: str) -> bool:
    p = snapshot_linha(cur, user_id, linha_id)
    return enfileirar(cur, user_id, "vida_snapshot", p) if p else enfileirar_remocao(
        cur, user_id, recurso=f"linha:{linha_id}", linha_id=linha_id)


def enfileirar_remocao(cur, user_id: str, *, recurso: str = None,
                       no_id: str = None, linha_id: str = None, ramo=False) -> bool:
    return enfileirar(cur, user_id, "vida_remover", {
        "recurso": recurso or (f"linha:{linha_id}" if linha_id else f"no:{no_id}"),
        "no_id": str(no_id) if no_id else None,
        "linha_id": str(linha_id) if linha_id else None,
        "ramo": bool(ramo),
    })


def _fragmentos(texto: str) -> list[str]:
    texto = "\n".join(l.strip() for l in str(texto or "").splitlines()).strip()
    if not texto:
        return []
    paragrafos = [p.strip() for p in texto.split("\n") if p.strip()]
    saida, atual = [], ""
    for p in paragrafos:
        pedacos = [p[i:i + _TAMANHO_FRAGMENTO] for i in range(0, len(p), _TAMANHO_FRAGMENTO)] or [p]
        for pedaco in pedacos:
            if atual and len(atual) + 1 + len(pedaco) > _TAMANHO_FRAGMENTO:
                saida.append(atual)
                atual = ""
            if len(saida) >= _MAX_FRAGMENTOS:
                break
            atual = f"{atual}\n{pedaco}".strip()
        if len(saida) >= _MAX_FRAGMENTOS:
            break
    if atual and len(saida) < _MAX_FRAGMENTOS:
        saida.append(atual)
    return saida


def _hash_payload(p: dict) -> str:
    bruto = json.dumps(p, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def _apagar_derivadas(alvo, user_id: str, p: dict) -> int:
    recurso, no_id = str(p.get("recurso") or ""), str(p.get("no_id") or "")
    ramo = bool(p.get("ramo"))
    n = 0
    for memoria in list(alvo.store.all(NAMESPACE)):
        md = memoria.metadata or {}
        if md.get("origem") != _ORIGEM or str(md.get("ownerId") or "") != str(user_id):
            continue
        casa = recurso and str(md.get("recurso") or "") == recurso
        if ramo and no_id:
            ancestrais = md.get("ancestrais") if isinstance(md.get("ancestrais"), list) else []
            casa = casa or str(md.get("no_id") or "") == no_id or no_id in map(str, ancestrais)
        if casa and alvo.store.delete(NAMESPACE, memoria.id):
            n += 1
    return n


def frase(tipo: str, p: dict) -> str:
    """O texto tem que ser FRASE, não log. O embedder é semântico: "linha 8f2a
    atualizada: status=feito" não se parece com nada que alguém vá perguntar depois."""
    nome = p.get("nome") or p.get("titulo") or "algo"
    data = p.get("data") or ""
    dias = p.get("dias")
    if tipo in ("habito_streak_7", "habito_streak_30", "habito_streak_100"):
        return f"Manteve o hábito '{nome}' por {dias} dias seguidos, até {data}."
    if tipo == "habito_abandonado":
        return f"Está há {dias} dias sem marcar o hábito '{nome}' (último em {data})."
    if tipo == "sequencia_quebrada":
        return f"Quebrou uma sequência de {dias} dias no hábito '{nome}' em {data}."
    if tipo == "projeto_concluido":
        dur = f" depois de {dias} dias" if dias else ""
        return f"Concluiu o projeto '{nome}'{dur}, em {data}."
    if tipo == "meta_concluida":
        return f"Bateu a meta '{nome}' em {data}."
    if tipo == "leitura_concluida":
        autor = f" de {p['autor']}" if p.get("autor") else ""
        nota = f", e deu nota {p['nota']} de 5" if p.get("nota") else ""
        return f"Terminou '{nome}'{autor} em {data}{nota}."
    if tipo == "diario_do_dia":
        humor = f" Humor: {p['humor']}." if p.get("humor") else ""
        trecho = (p.get("trecho") or "").strip()[:400]
        return f"No diário de {data}: {trecho}{humor}"
    if tipo == "nivel_subiu":
        return f"Chegou ao nível {p.get('nivel')} ({p.get('rank')}) em {data}."
    return f"{tipo} em {data}: {nome}"


def metadados(tipo: str, user_id: str, p: dict) -> dict:
    """`origem: banco` é o que permite três coisas: filtrar o recall, APAGAR tudo
    que veio do Banco de dados com um filtro só (reversibilidade), e ligar a memória de
    volta à linha que a gerou."""
    origem = _ORIGEM if tipo.startswith("vida_") else "banco"
    md = {
        "origem": origem,
        "source": _ORIGEM if tipo.startswith("vida_") else "banco",
        "tipo_evento": tipo,
        "user_id": user_id,
        "ownerId": user_id,
    }
    if tipo.startswith("vida_"):
        md["life_scope"] = "owner"
    for k in ("recurso", "recurso_tipo", "recurso_id", "no_id", "linha_id",
              "modelo", "titulo", "data"):
        if p.get(k):
            md[k] = str(p[k])
    if isinstance(p.get("ancestrais"), list):
        md["ancestrais"] = [str(x) for x in p["ancestrais"]]
    return md


def drenar(mind, pool, lote: int = 50, ceder_se_leitura_ha=1.5,
           maximo_adiamento=5.0) -> int:
    """Drena a caixa de saída. Chamado pela thread daemon, nunca por um handler.

    A contrapressão reusa o `_last_read_at` que o store já mantém — o mesmo sinal que
    o dream usa para ceder quando há conversa ou recall ativo. Inventar um segundo
    mecanismo para o mesmo problema é como dois relógios discordam."""
    if not ligada():
        return 0
    agora = time.monotonic()
    ultima = getattr(getattr(mind, "store", None), "_last_read_at", None)
    ultimo_dreno = getattr(mind, "_vida_ponte_ultimo_dreno", agora)
    if (ultima is not None and (agora - ultima) < ceder_se_leitura_ha
            and (agora - ultimo_dreno) < maximo_adiamento):
        return 0        # recall recente ganha prioridade, mas não pode causar fome eterna

    feitos = 0
    with pool.connection() as con, con.cursor() as cur:
        cur.execute("SET search_path TO banco, public")
        cur.execute("SELECT id,user_id,tipo,payload FROM banco.evento_pendente "
                    "WHERE processado_em IS NULL AND tentativas < 5 ORDER BY id LIMIT %s", (lote,))
        pendentes = cur.fetchall()
        for ident, user_id, tipo, payload in pendentes:
            vira, usa_remember, importancia = REGRAS.get(tipo, (False, False, 0.0))
            if not vira:
                cur.execute("UPDATE banco.evento_pendente SET processado_em=now() WHERE id=%s",
                            (ident,))
                continue
            try:
                alvo = mind.for_namespace(NAMESPACE)
                payload = payload or {}
                if tipo == "vida_remover":
                    _apagar_derivadas(alvo, user_id, payload)
                elif tipo == "vida_snapshot":
                    # Estado atual, não histórico: remove a versão anterior e grava
                    # fragmentos sem extração LLM. O hash permite backfill idempotente.
                    _apagar_derivadas(alvo, user_id, payload)
                    partes = _fragmentos(payload.get("texto") or "")
                    base_md = metadados(tipo, user_id, payload)
                    base_md["conteudo_hash"] = _hash_payload(payload)
                    for i, parte in enumerate(partes):
                        md = {**base_md, "fragmento": i + 1, "fragmentos": len(partes)}
                        titulo = payload.get("titulo") or "Logica Life"
                        texto = parte if i == 0 else f"{titulo}.\n{parte}"
                        alvo.remember(
                            texto,
                            metadata=md,
                            importance=importancia,
                            tags=["logica-life", f"owner:{user_id}"],
                            session=str(payload.get("recurso") or "logica-life"),
                            extract=False,
                        )
                elif usa_remember:
                    alvo.remember(frase(tipo, payload), metadata=metadados(tipo, user_id, payload),
                                  importance=importancia)
                else:
                    # log(): episódico cru, SEM extração e SEM dedup. É o que torna
                    # evento repetível seguro.
                    alvo.log(frase(tipo, payload), metadata=metadados(tipo, user_id, payload))
                cur.execute("UPDATE banco.evento_pendente SET processado_em=now() WHERE id=%s",
                            (ident,))
                feitos += 1
            except Exception as e:
                cur.execute("UPDATE banco.evento_pendente SET tentativas=tentativas+1, "
                            "erro=%s WHERE id=%s", (repr(e)[:500], ident))
                print(f"[ponte] evento {ident} falhou: {e}", file=sys.stderr)
    mind._vida_ponte_ultimo_dreno = time.monotonic()
    return feitos


def sincronizar_existente(mind, pool) -> dict:
    """Backfill idempotente no boot.

    Compara o hash do estado atual com o que já está no namespace ``vida``. Isso
    inclui conteúdo criado antes desta ponte existir e também limpa fragmentos que
    ficaram órfãos após uma remoção ocorrida com o Mind desligado.
    """
    existentes = {}
    alvo = mind.for_namespace(NAMESPACE)
    for memoria in alvo.store.all(NAMESPACE):
        md = memoria.metadata or {}
        if md.get("origem") != _ORIGEM or not md.get("recurso") or not md.get("ownerId"):
            continue
        existentes[(str(md["ownerId"]), str(md["recurso"]))] = str(md.get("conteudo_hash") or "")

    ativos, enfileirados = set(), 0
    with pool.connection() as con, con.cursor() as cur:
        cur.execute("SET search_path TO banco, public")
        cur.execute("SELECT user_id,id FROM banco.no WHERE arquivado_em IS NULL ORDER BY user_id,id")
        nos = [(str(u), str(i)) for u, i in cur.fetchall()]
        cur.execute(
            "SELECT l.user_id,l.id FROM banco.linha l JOIN banco.no n "
            "ON n.id=l.no_id AND n.user_id=l.user_id "
            "WHERE l.deletado_em IS NULL AND l.arquivado_em IS NULL "
            "AND n.arquivado_em IS NULL ORDER BY l.user_id,l.id"
        )
        linhas = [(str(u), str(i)) for u, i in cur.fetchall()]
        for user_id, ident in nos:
            p = snapshot_no(cur, user_id, ident)
            if not p:
                continue
            chave = (user_id, p["recurso"])
            ativos.add(chave)
            if existentes.get(chave) != _hash_payload(p):
                enfileirados += int(enfileirar(cur, user_id, "vida_snapshot", p))
        for user_id, ident in linhas:
            p = snapshot_linha(cur, user_id, ident)
            if not p:
                continue
            chave = (user_id, p["recurso"])
            ativos.add(chave)
            if existentes.get(chave) != _hash_payload(p):
                enfileirados += int(enfileirar(cur, user_id, "vida_snapshot", p))
        for (user_id, recurso) in set(existentes) - ativos:
            tipo, _, ident = recurso.partition(":")
            enfileirados += int(enfileirar_remocao(
                cur, user_id, recurso=recurso,
                no_id=ident if tipo == "no" else None,
                linha_id=ident if tipo == "linha" else None,
                ramo=tipo == "no",
            ))
    return {"ativos": len(ativos), "enfileirados": enfileirados,
            "orfaos": len(set(existentes) - ativos)}


def iniciar_daemon(mind, pool, intervalo: int = None) -> threading.Thread:
    """UMA thread, fora do pool HTTP. Fail-soft: nunca levanta, nunca bloqueia."""
    intervalo = intervalo or int(os.environ.get("LM_VIDA_PONTE_INTERVALO", "20") or 20)
    if not ligada() or intervalo <= 0:
        print("[ponte] ponte Banco de dados->Memória DESLIGADA", file=sys.stderr)
        return None

    def laco():
        try:
            r = sincronizar_existente(mind, pool)
            print(f"[ponte] backfill: {r['ativos']} recursos, "
                  f"{r['enfileirados']} pendentes, {r['orfaos']} órfãos", file=sys.stderr)
        except Exception as e:
            print(f"[ponte] backfill falhou: {e}", file=sys.stderr)
        while True:
            try:
                n = drenar(mind, pool)
                if n:
                    print(f"[ponte] {n} eventos viraram memória em '{NAMESPACE}'", file=sys.stderr)
            except Exception as e:
                print(f"[ponte] ciclo falhou: {e}", file=sys.stderr)
            time.sleep(intervalo)

    t = threading.Thread(target=laco, name="lm-ponte-vida", daemon=True)
    t.start()
    print(f"[ponte] ligada: namespace '{NAMESPACE}', a cada {intervalo}s", file=sys.stderr)
    return t


def apagar_memorias_do_banco(mind, user_id: str = None) -> int:
    """Reversibilidade. `origem: banco` nos metadados existe exatamente para isto:
    desligar a ponte e limpar o que ela escreveu, sem tocar no resto da memória."""
    alvo = mind.for_namespace(NAMESPACE)
    filtro = {"origem": "banco"}
    if user_id:
        filtro["user_id"] = user_id
    n = 0
    for m in alvo.store.all(NAMESPACE):
        md = m.metadata or {}
        if all(md.get(k) == v for k, v in filtro.items()):
            alvo.store.delete(NAMESPACE, m.id)
            n += 1
    return n
