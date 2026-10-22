"""A read-only, paginated library over canonical memory. No migration or deletion.

Legacy records are classified at query time, before LIMIT. Technical history is
retained with its original ID/content, but never presented as a durable fact.
"""
import json
import re

COLLECTIONS = ("knowledge", "decisions", "conversations", "executions", "system", "review")


def consolidation_evidence(memory):
    """Only conversational/knowledge-bearing evidence enters consolidation.

    System telemetry, tool protocols and hypotheses stay available in their own
    collections, without consuming the fact extractor's newest-record window.
    """
    view = present(memory)
    collection = view['presentation']['collection']
    if collection in ('system', 'review', 'executions'):
        return None
    role = (memory.metadata or {}).get('role') or 'unknown'
    text = view['presentation']['body']
    if not text.strip():
        return None
    return f"[source_id={memory.id}; role={role}; collection={collection}]\n{text[:8000]}"


def is_atomic_prose(text):
    text = (text or '').strip()
    return bool(12 <= len(text) <= 1200 and not text.startswith(('{', '['))
                and not re.search(r'```|<tool_call>|DSML', text))


def collection_sql(pg=False):
    def meta(key):
        return f"COALESCE(metadata->>'{key}','')" if pg else f"COALESCE(json_extract(metadata,'$.{key}'),'')"
    kind, source = meta("type"), meta("source")
    expression = f"""CASE
      WHEN {source} = 'anima-bus' OR content LIKE 'Organism signals%'
        OR id LIKE 'self-model::%' OR {kind} IN ('self_model','self-model','telemetry','heartbeat') THEN 'system'
      WHEN {kind} IN ('synapse_capsule','capsule','mentor_review','session_output','run_record')
        OR CAST({meta('record')} AS TEXT) IN ('true','1') OR {meta('of_record')} <> ''
        OR content LIKE '%"capsule_id":%' OR content LIKE '%"mentor_slug":%' THEN 'executions'
      WHEN {kind} IN ('conversation','turn','chat','cli_conversation_turn')
        OR {source} LIKE 'cli:%auto-capture' OR {source} = 'cli-conversation'
        OR content LIKE '%"kind": "cli_conversation_turn"%' THEN 'conversations'
      WHEN id LIKE 'hyp::%' OR {kind} IN ('hypothesis','hypotheses')
        OR {meta('continuity')} = 'world-insights'
        OR ltrim(content) LIKE '{{%' OR ltrim(content) LIKE '[%'
        OR content LIKE '%```%' OR content LIKE '%<tool_call>%' OR content LIKE '%DSML%' THEN 'review'
      WHEN {kind} IN ('decision','decisao','recorded_decision') OR {meta('memoryKind')} = 'decision' THEN 'decisions'
      WHEN layer IN ('semantic','user','graph') THEN 'knowledge'
      WHEN layer = 'episodic' THEN 'conversations'
      ELSE 'review' END"""
    return expression.replace('%', '%%') if pg else expression


def library_queries(table, columns, *, pg=False, namespace=None, metadata_filter=None,
                    collection="knowledge", query="", dimension=None, category=None,
                    layer=None, memory_id=None, limit=20, offset=0):
    """Bound values only. Classification and privacy precede counts/pagination."""
    if collection not in (*COLLECTIONS, "all"):
        raise ValueError("invalid memory collection")
    p = "%s" if pg else "?"
    def meta(key):
        return f"metadata->>'{key}'" if pg else f"json_extract(metadata,'$.{key}')"
    where = ["namespace NOT LIKE 'private-cli-%%'" if pg else "namespace NOT LIKE 'private-cli-%'", f"COALESCE({meta('memoryScope')},'shared') <> 'personal'"]
    # Aliases are graph bookkeeping, never standalone memories.
    where.append("NOT (COALESCE(tags,'[]'::jsonb) @> '[\"alias\"]'::jsonb)" if pg else "NOT EXISTS (SELECT 1 FROM json_each(tags) WHERE value='alias')")
    values = []
    if namespace:
        where.append(f"namespace={p}"); values.append(namespace)
    for key, value in (metadata_filter or {}).items():
        if key in ("ownerId", "project", "actorId", "memoryScope"):
            where.append(f"{meta(key)}={p}"); values.append(value)
    for key, value in (("dimension", dimension), ("category", category)):
        if value:
            where.append(f"{meta(key)}={p}"); values.append(value)
    if layer:
        where.append(f"layer={p}"); values.append(layer)
    if memory_id:
        where.append(f"id={p}"); values.append(memory_id)
    if query:
        # Literal substring search, including %/_ typed by the person.
        literal = query.lower().replace("!", "!!").replace("%", "!%").replace("_", "!_")
        where.append(f"(LOWER(content) LIKE {p} ESCAPE '!' OR LOWER(COALESCE({meta('title')},'')) LIKE {p} ESCAPE '!')")
        values.extend([f"%{literal}%"] * 2)
    base = " AND ".join(where)
    expression = collection_sql(pg)
    counts = (f"SELECT {expression} AS collection, COUNT(*) FROM {table} WHERE {base} GROUP BY 1", list(values))
    if collection != "all":
        base += f" AND ({expression})={p}"; values.append(collection)
    page = (f"SELECT {columns} FROM {table} WHERE {base} ORDER BY created_at DESC, seq DESC, id DESC LIMIT {p} OFFSET {p}",
            values + [limit, offset])
    return counts, page


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def present(memory):
    """Human-readable projection. Raw content is preserved separately, never executed."""
    m = memory.to_dict() if hasattr(memory, 'to_dict') else dict(memory)
    md, content = m.get("metadata") or {}, m.get("content") or ""
    data = None
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        pass
    kind = md.get("type", "")
    ns = m.get("namespace", "")
    collection = "knowledge" if m.get("layer") in ("semantic", "user", "graph") else "conversations"
    title, body, status = _text(md.get("title")), content, None
    if md.get("source") == "anima-bus" or content.startswith("Organism signals") or str(m.get("id", "")).startswith("self-model::") or kind in ("self_model", "self-model", "telemetry", "heartbeat"):
        collection = "system"
        title = f"Estado de {ns}" if str(m.get("id", "")).startswith("self-model::") else "Sinais do sistema"
        body = "Registro operacional preservado para diagnóstico."
        if content.startswith("Organism signals"):
            count = re.search(r": (\d+) sinais", content)
            body = f"{count.group(1)} sinais registrados pelo organismo." if count else body
    elif kind in ("synapse_capsule", "capsule", "mentor_review", "session_output", "run_record") or md.get('record') or md.get('of_record') or isinstance(data, dict) and ("capsule_id" in data or "mentor_slug" in data):
        collection = "executions"
        if isinstance(data, dict):
            output = data.get("output")
            body = _text(output) or (_text(output.get("sanitized")) or _text(output.get("summary")) if isinstance(output, dict) else "")
            inp = data.get("input") or {}
            task = _text(data.get("task")) or (_text(inp.get("task")) if isinstance(inp, dict) else "")
            title = task or f"Execução de {data.get('agent_name') or data.get('mentor_slug') or ns}"
            status = data.get("status") or (data.get("meta") or {}).get("api_error")
            if not body:
                body = "Registro de execução. Consulte o original para os detalhes técnicos."
        else:
            title = title or f"Resultado de {ns}"
    elif kind in ("conversation", "turn", "chat", "cli_conversation_turn") or re.match(r"cli:.*auto-capture$", md.get("source", "")) or md.get("source") == "cli-conversation" or isinstance(data, dict) and data.get("kind") == "cli_conversation_turn":
        collection = "conversations"
        title = "Conversa com " + ns
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            body = "\n\n".join(f"**{'Você' if msg.get('role') == 'user' else 'Agente'}**\n{_text(msg.get('content'))}" for msg in data["messages"] if isinstance(msg, dict))
            status = data.get("status")
    elif str(m.get("id", "")).startswith("hyp::") or kind in ("hypothesis", "hypotheses") or md.get('continuity') == 'world-insights' or content.lstrip().startswith(("{", "[")) or re.search(r"```|<tool_call>|DSML", content):
        collection = "review"
        title = "Observação compartilhada a revisar" if md.get('continuity') == 'world-insights' else "Hipótese a revisar" if str(m.get("id", "")).startswith("hyp::") or kind in ("hypothesis", "hypotheses") else "Conteúdo a revisar"
        if isinstance(data, (dict, list)):
            body = "Conteúdo estruturado preservado no registro original. Revise sua origem antes de tratá-lo como conhecimento."
    elif kind in ("decision", "decisao", "recorded_decision") or md.get('memoryKind') == 'decision':
        collection = "decisions"
    clean = re.sub(r"```[\s\S]*?(?:```|$)", " [Trecho de código no original] ", body)
    clean = re.sub(r"<tool_call>[\s\S]*?(?:</tool_call>|$)", " [Registro de ferramenta no original] ", clean)
    if re.match(r"\s*<[|｜]{1,2}DSML", clean):
        clean = "Saída técnica de ferramenta. Este registro não é um fato confirmado."
    preview = re.sub(r"\s+", " ", clean).strip()
    if not title:
        title = re.sub(r"^[#*\s]+", "", preview).split(". ")[0][:100] or "Memória"
    m["presentation"] = {"collection": collection, "title": title[:160], "preview": preview[:360],
                         "body": clean, "status": status, "technical": collection in ("executions", "system", "review"),
                         "source": md.get("source") or (md.get("agent") if ns == "__world__" else None) or kind or ns}
    return m


def shared_prose_where(pg=False):
    meta = "COALESCE(metadata->>'memoryScope','shared')" if pg else "COALESCE(json_extract(metadata,'$.memoryScope'),'shared')"
    private = "private-cli-%%" if pg else "private-cli-%"
    return f"namespace NOT LIKE '{private}' AND {meta} <> 'personal' AND ({collection_sql(pg)}) IN ('knowledge','decisions','conversations')"
