import { useEffect, useState } from "react";
import { X, AlignLeft, UserRound, MessagesSquare, Calendar, Plug, Gauge, Tag, Hash, GitBranch, Network, CornerUpLeft, ArrowRight, Link2 } from "lucide-react";
import { api, tShort, type Memory, type Connections } from "../api";
import { LayerPill, SourceBadge } from "./MemoryCard";
import Markdown from "./Markdown";
import { dimColor } from "../lifearea";
import { useNav } from "../navctx";
import { useI18n } from "../i18n";

// Obsidian-style note pane: a memory opened as a document — a Properties panel
// (type/agent/session/date/source/tags) over the content, its provenance ("why
// do I believe this?"), and a CONNECTED panel of auto-derived links you can walk
// — entities it mentions, the relations among them, and other notes that touch
// the same entities or category. Obsidian needs hand-typed [[links]]; here the
// graph IS the links.
function Prop({ icon: Icon, k, children }: { icon: any; k: string; children: any }) {
  return (
    <div className="flex items-start gap-3 py-[5px] text-[13px]">
      <span className="flex items-center gap-2 text-[var(--dim)] w-[88px] flex-none">
        <Icon size={14} /> {k}
      </span>
      <span className="text-[var(--txt)] min-w-0 break-words">{children}</span>
    </div>
  );
}

// a connected note, rendered as a walkable mini-card
function MiniNote({ m, onOpen }: { m: Memory; onOpen: () => void }) {
  const cat = m.metadata?.category;
  return (
    <button onClick={onOpen}
      className="w-full text-left card-surface px-3 py-2 hover:border-[var(--accent)]/60 hover:bg-[var(--panel2)] transition group">
      <div className="flex items-center gap-2 mb-1">
        <LayerPill layer={m.layer} />
        {cat && (() => { const dc = dimColor(m.metadata?.dimension); return (
          <span className="text-[10px] font-semibold px-1.5 py-px rounded-full" style={{ background: `${dc}1f`, color: dc }}>{cat}</span>
        ); })()}
        <ArrowRight size={13} className="ml-auto text-[var(--dim2)] opacity-0 group-hover:opacity-100" />
      </div>
      <div className="text-[13px] text-[var(--txt)] line-clamp-2">{m.content}</div>
    </button>
  );
}

export default function MemoryDetail({ memory, onClose }: { memory: Memory; onClose: () => void }) {
  const { t } = useI18n();
  const { onEntity } = useNav();
  // the pane is walkable — clicking a connected note swaps `cur` (with a back stack)
  const [cur, setCur] = useState<Memory>(memory);
  const [stack, setStack] = useState<Memory[]>([]);
  const [prov, setProv] = useState<{ from: Memory[]; supersedes?: string }>({ from: [] });
  const [conn, setConn] = useState<Connections | null>(null);
  const md = cur.metadata || {};

  useEffect(() => { setCur(memory); setStack([]); }, [memory.id, memory.namespace]);

  useEffect(() => {
    api.provenance(cur.namespace, cur.id).then((d) => setProv({ from: d.from || [], supersedes: d.supersedes }))
      .catch(() => setProv({ from: [] }));
    setConn(null);
    api.connected(cur.namespace, cur.id).then(setConn).catch(() => setConn({ entities: [], relations: [], mentions: [], siblings: [] }));
  }, [cur.id, cur.namespace]);

  const walkTo = (m: Memory) => { setStack((s) => [...s, cur]); setCur(m); };
  const back = () => setStack((s) => { if (!s.length) return s; setCur(s[s.length - 1]); return s.slice(0, -1); });
  const goEntity = (name: string) => onEntity(cur.namespace, name);

  const hasConn = conn && (conn.entities.length || conn.relations.length || conn.mentions.length || conn.siblings.length);

  return (
    <div className="fixed inset-0 z-[55]" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[1px]" />
      <div onClick={(e) => e.stopPropagation()}
        className="absolute right-0 top-0 bottom-0 w-[560px] max-w-full bg-[var(--bg2)] border-l border-[var(--line)]
          shadow-[var(--shadow)] overflow-y-auto fadein">
        <div className="sticky top-0 bg-[var(--bg2)] border-b border-[var(--line)] px-6 py-3 flex items-center gap-2 z-10">
          {stack.length > 0 && (
            <button onClick={back} className="text-[var(--dim)] hover:text-[var(--txt)] -ml-1" title={t("back")}><CornerUpLeft size={16} /></button>
          )}
          <span className="text-[var(--dim2)] text-[12px]">{cur.namespace} / {cur.layer}</span>
          <button onClick={onClose} className="ml-auto text-[var(--dim)] hover:text-[var(--txt)]"><X size={18} /></button>
        </div>

        <div className="px-6 py-5">
          <h1 className="text-[22px] font-bold leading-tight m-0 mb-4 break-words">{cur.content.slice(0, 120)}{cur.content.length > 120 ? "…" : ""}</h1>

          {/* Properties (Obsidian-style) */}
          <div className="text-[var(--dim2)] text-[13px] font-semibold mb-1.5">{t("properties")}</div>
          <div className="border-y border-[var(--line)] py-1.5 mb-5">
            <Prop icon={AlignLeft} k={t("type_word")}><LayerPill layer={cur.layer} /></Prop>
            <Prop icon={UserRound} k={t("prop_agent")}>{cur.namespace}</Prop>
            {md.session && <Prop icon={MessagesSquare} k={t("prop_session")}>{md.session}</Prop>}
            <Prop icon={Calendar} k={t("prop_date")}>{tShort(cur.created_at)}</Prop>
            {md.category && <Prop icon={Tag} k={t("prop_category")}><span className="text-[12px] font-semibold px-2 py-px rounded-full" style={{ background: `${dimColor(md.dimension)}1f`, color: dimColor(md.dimension) }}>{md.category}</span></Prop>}
            {md.source && <Prop icon={Plug} k={t("prop_source")}><SourceBadge source={md.source} /></Prop>}
            <Prop icon={Gauge} k={t("prop_importance")}>{(cur.importance ?? 0).toFixed(2)}</Prop>
            {cur.tags && cur.tags.length > 0 && (
              <Prop icon={Tag} k={t("prop_tags")}>{cur.tags.map((tg) => <span key={tg} className="inline-block text-[var(--accent2)] bg-[var(--panel2)] border border-[var(--line)] px-1.5 rounded mr-1 text-[11.5px]">#{tg}</span>)}</Prop>
            )}
            {(md.subject || md.predicate) && (
              <Prop icon={GitBranch} k={t("prop_relation")}><span className="text-[var(--accent2)]">{md.subject} {md.predicate} {md.object}</span></Prop>
            )}
            <Prop icon={Hash} k={t("prop_id")}><span className="text-[var(--dim2)] text-[11px] font-mono">{cur.id}</span></Prop>
          </div>

          {/* Content — Markdown + clickable [[wikilinks]] */}
          <Markdown text={cur.content} onWiki={goEntity} className="text-[15px] leading-[1.7] break-words" />

          {/* Connected — derived backlinks */}
          <div className="flex items-baseline gap-2 mt-7 mb-2">
            <span className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px] flex items-center gap-1.5"><Network size={13} /> {t("connected")}</span>
            <span className="text-[var(--dim2)] text-[11px]">{t("conn_sub")}</span>
          </div>

          {conn == null ? (
            <div className="text-[var(--dim)] text-[13px]">…</div>
          ) : !hasConn ? (
            <div className="text-[var(--dim)] text-[13px]">{t("conn_none")}</div>
          ) : (
            <div className="space-y-4">
              {conn.entities.length > 0 && (
                <div>
                  <div className="text-[var(--dim2)] text-[11px] mb-1.5">{t("conn_mentions")}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {conn.entities.map((e) => { const dc = dimColor(e.dimension); return (
                      <button key={e.name} onClick={() => goEntity(e.name)} title={e.type || undefined}
                        className="inline-flex items-center gap-1.5 text-[12px] px-2 py-1 rounded-lg border hover:bg-[var(--panel2)]"
                        style={{ borderColor: `${dc}55`, color: dc }}>
                        <span className="w-1.5 h-1.5 rounded-full" style={{ background: dc }} />{e.name}
                        {!!e.degree && <span className="tabular-nums text-[var(--dim2)]">{e.degree}</span>}
                      </button>
                    ); })}
                  </div>
                </div>
              )}

              {conn.relations.length > 0 && (
                <div>
                  <div className="text-[var(--dim2)] text-[11px] mb-1.5">{t("conn_relations")}</div>
                  <div className="space-y-1">
                    {conn.relations.map((r, i) => (
                      <div key={r.id || i} className={`text-[12.5px] flex items-center gap-1.5 flex-wrap ${r.valid ? "" : "opacity-55 line-through decoration-[var(--dim2)]"}`}>
                        <button onClick={() => goEntity(r.subject)} className="text-[var(--accent2)] hover:underline">{r.subject}</button>
                        <span className="text-[var(--dim)]">{r.predicate}</span>
                        <button onClick={() => goEntity(r.object)} className="text-[var(--accent2)] hover:underline">{r.object}</button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {conn.mentions.length > 0 && (
                <div>
                  <div className="text-[var(--dim2)] text-[11px] mb-1.5 flex items-center gap-1.5"><Link2 size={12} /> {t("conn_backlinks")}</div>
                  <div className="space-y-2">{conn.mentions.map((m) => <MiniNote key={m.id} m={m} onOpen={() => walkTo(m)} />)}</div>
                </div>
              )}

              {conn.siblings.length > 0 && (
                <div>
                  <div className="text-[var(--dim2)] text-[11px] mb-1.5">{t("conn_related")}</div>
                  <div className="space-y-2">{conn.siblings.map((m) => <MiniNote key={m.id} m={m} onOpen={() => walkTo(m)} />)}</div>
                </div>
              )}
            </div>
          )}

          {/* Provenance — why do I believe this? */}
          <div className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px] mt-7 mb-2">{t("why_believe")}</div>
          {prov.from.length ? (
            <div className="space-y-2">
              {prov.from.map((s) => (
                <div key={s.id} className="card-surface px-3.5 py-2.5">
                  <div className="flex items-center gap-2 mb-1"><LayerPill layer={s.layer} /><SourceBadge source={(s.metadata || {}).source} /><span className="text-[var(--dim2)] text-[11px] ml-auto">{tShort(s.created_at)}</span></div>
                  <div className="text-[13.5px]">{s.content}</div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-[var(--dim)] text-[13px]">
              {cur.tags?.includes("distilled") || cur.tags?.includes("inferred")
                ? t("prov_distilled")
                : t("prov_direct")}
              {prov.supersedes && <span> · {t("prov_supersedes")}</span>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
