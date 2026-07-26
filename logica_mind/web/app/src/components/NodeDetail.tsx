import { useEffect, useState } from "react";
import { X, GitCommitHorizontal, Trash2, Locate } from "lucide-react";
import { api, tShort, type Memory } from "../api";
import MemoryCard from "./MemoryCard";
import { useI18n } from "../i18n";

// Obsidian-style: click an entity → see what's there. Connected entities as chips
// (click one to walk the graph) + every memory that mentions it (graph facts +
// notes), each clickable to open it in the Memories view.
export default function NodeDetail({
  ns, name, onClose, onOpenMemory, onPickEntity, onFocus,
}: {
  ns: string; name: string; onClose: () => void;
  onOpenMemory: (m: Memory) => void; onPickEntity: (n: string) => void;
  onFocus?: (n: string) => void;
}) {
  const { t } = useI18n();
  const [connected, setConnected] = useState<string[]>([]);
  const [unlinked, setUnlinked] = useState<{ entity: string; count: number }[]>([]);
  const [mems, setMems] = useState<Memory[]>([]);
  const [info, setInfo] = useState<{ type: string; aliases: string[] }>({ type: "", aliases: [] });
  const [loading, setLoading] = useState(true);
  const [erasing, setErasing] = useState(false);
  const [eraseConfirm, setEraseConfirm] = useState(false);
  const [erased, setErased] = useState(false);
  const [mergeTo, setMergeTo] = useState("");
  const [merging, setMerging] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true); setUnlinked([]);
    api.node(ns, name).then((d) => {
      if (!alive) return;
      setConnected(d.connected || []); setMems(d.memories || []);
      setInfo({ type: d.type || "", aliases: d.aliases || [] }); setLoading(false);
    }).catch(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [ns, name]);

  // unlinked mentions load lazily (the panel is already open) — a multi-second graph
  // scan that must never block showing the entity's memories
  useEffect(() => {
    let alive = true;
    api.nodeUnlinked(ns, name).then((d) => { if (alive) setUnlinked(d.unlinked || []); }).catch(() => {});
    return () => { alive = false; };
  }, [ns, name]);

  return (
    <div className="absolute top-3 left-3 z-[4] w-[340px] max-w-[84vw] max-h-[calc(100%-24px)] overflow-y-auto
      glass border border-[var(--line)] rounded-[14px] p-4 shadow-[var(--shadow)] fadein">
      <button onClick={onClose} className="absolute top-2.5 right-3 text-[var(--dim)] hover:text-[var(--txt)]"><X size={16} /></button>
      <h3 className="m-0 text-[16px] font-bold pr-6 break-words">{name}
        {info.type && <span className="ml-2 text-[10px] font-semibold uppercase tracking-wide text-[var(--accent2)] bg-[var(--panel2)] border border-[var(--line)] px-1.5 py-[1px] rounded align-middle">{info.type}</span>}
      </h3>
      {info.aliases.length > 0 && (
        <div className="text-[var(--dim2)] text-[11.5px] mt-0.5">{t("aliases")}: {info.aliases.join(", ")}</div>
      )}

      {onFocus && (
        <button onClick={() => onFocus(name)} title={t("graph_focus_here")}
          className="mt-2 flex items-center gap-1.5 text-[11.5px] text-[var(--accent)] hover:underline">
          <Locate size={12} /> {t("graph_focus_here")}
        </button>
      )}

      {/* GDPR erase button */}
      {!erased && (
        <div className="mt-2">
          {!eraseConfirm ? (
            <button onClick={() => setEraseConfirm(true)}
              className="flex items-center gap-1.5 text-[11px] text-[var(--dim2)] hover:text-[#fb7185] transition">
              <Trash2 size={11} /> {t("forget_entity")}
            </button>
          ) : (
            <div className="flex items-center gap-2 mt-1">
              <span className="text-[11px] text-[#fb7185]">{t("forget_entity_confirm")} "{name}"?</span>
              <button disabled={erasing} onClick={async () => {
                setErasing(true);
                await api.forgetAbout(ns, name).catch(() => {});
                setErasing(false); setErased(true); setEraseConfirm(false);
              }} className="text-[11px] text-[#fb7185] border border-[#fb718550] rounded px-2 py-0.5 hover:bg-[#fb718520] disabled:opacity-40">
                {erasing ? t("erasing") : t("forget_entity_btn")}
              </button>
              <button onClick={() => setEraseConfirm(false)} className="text-[11px] text-[var(--dim)] hover:text-[var(--txt)]">
                <X size={12} />
              </button>
            </div>
          )}
        </div>
      )}
      {erased && <div className="text-[11px] text-[var(--dim)] mt-1.5">✓ {t("erased")}</div>}

      {/* rename / merge — non-destructive alias: this entity resolves to the target
          from now on, and the graph collapses the nodes everywhere */}
      <div className="mt-2 flex items-center gap-1.5">
        <input value={mergeTo} onChange={(e) => setMergeTo(e.target.value)}
          onKeyDown={(e) => e.stopPropagation()}
          placeholder={t("node_merge_placeholder")}
          className="flex-1 min-w-0 bg-[var(--panel2)] border border-[var(--line)] rounded-lg px-2 py-1 text-[11.5px] outline-none text-[var(--txt)]" />
        <button disabled={!mergeTo.trim() || merging} onClick={async () => {
          setMerging(true);
          try {
            const r = await api.entityAlias(ns, name, mergeTo.trim());
            setMergeTo(""); onPickEntity(r.canonical || mergeTo.trim());
          } catch { /* fail-soft */ }
          setMerging(false);
        }} className="text-[11px] border border-[var(--line)] rounded-lg px-2 py-1 text-[var(--dim)] hover:text-[var(--txt)] disabled:opacity-40 flex-none">
          {merging ? "…" : t("node_merge_btn")}
        </button>
      </div>
      <div className="text-[var(--dim)] text-[12px] mt-0.5">
        {connected.length} {t("connected").toLowerCase()} · {mems.length} {t("memories").toLowerCase()}
      </div>

      {connected.length > 0 && (
        <>
          <div className="text-[var(--dim2)] text-[10px] uppercase tracking-[.7px] mt-3.5 mb-2">{t("connected")}</div>
          <div className="flex flex-wrap gap-1.5">
            {connected.map((c) => (
              <button key={c} onClick={() => onPickEntity(c)}
                className="px-2.5 py-1 rounded-full text-[12px] border border-[var(--line)] text-[var(--dim)]
                  hover:text-[var(--txt)] hover:border-[var(--accent)]/60 hover:bg-[var(--panel2)]">{c}</button>
            ))}
          </div>
        </>
      )}

      {/* unlinked mentions — co-mentioned but with no explicit edge (Obsidian, but it knows the entities) */}
      {unlinked.length > 0 && (
        <>
          <div className="text-[var(--dim2)] text-[10px] uppercase tracking-[.7px] mt-3.5 mb-2">{t("node_unlinked")}</div>
          <div className="flex flex-wrap gap-1.5">
            {unlinked.map((u) => (
              <button key={u.entity} onClick={() => onPickEntity(u.entity)} title={`${u.count}×`}
                className="px-2.5 py-1 rounded-full text-[12px] border border-dashed border-[#f59e0b]/50 text-[#f59e0b]
                  hover:bg-[#f59e0b]/10 inline-flex items-center gap-1.5">{u.entity}<span className="tabular-nums opacity-70">{u.count}</span></button>
            ))}
          </div>
        </>
      )}

      {/* entity lifecycle timeline — facts sorted chronologically, superseded shown as strikethrough */}
      {!loading && mems.length > 1 && (() => {
        const graphMems = mems.filter(m => m.layer === "graph" || m.layer === "semantic")
          .sort((a, b) => (a.created_at || "") < (b.created_at || "") ? -1 : 1);
        if (graphMems.length < 2) return null;
        const supersededIds = new Set(graphMems.map(m => m.metadata?.supersedes).filter(Boolean));
        return (
          <div className="mt-3.5 mb-1">
            <div className="text-[var(--dim2)] text-[10px] uppercase tracking-[.7px] mb-2 flex items-center gap-1.5">
              <GitCommitHorizontal size={11} /> {t("timeline")}
            </div>
            <div className="relative pl-4">
              <div className="absolute left-1.5 top-0 bottom-0 w-px bg-[var(--line)]" />
              {graphMems.map((m, i) => {
                const isSuperseded = supersededIds.has(m.id);
                const isCurrent = i === graphMems.length - 1;
                return (
                  <div key={m.id} className="relative mb-2 pl-3 cursor-pointer" onClick={() => onOpenMemory(m)}>
                    <div className={`absolute left-[-1px] top-1.5 w-2 h-2 rounded-full border-2
                      ${isCurrent ? "bg-[var(--accent)] border-[var(--accent)]"
                                  : isSuperseded ? "bg-transparent border-[var(--dim2)]"
                                                 : "bg-[var(--panel2)] border-[var(--accent2)]"}`} />
                    <div className={`text-[11.5px] leading-snug ${isSuperseded ? "line-through text-[var(--dim2)]" : "text-[var(--dim)]"}`}>
                      {m.content.slice(0, 70)}{m.content.length > 70 ? "…" : ""}
                    </div>
                    <div className="text-[10px] text-[var(--dim2)]">{tShort(m.created_at)?.slice(0, 10)}</div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })()}

      <div className="text-[var(--dim2)] text-[10px] uppercase tracking-[.7px] mt-3.5 mb-2">{t("memories")} · {t("click_to_open")}</div>
      {loading ? (
        <div className="text-[var(--dim)] text-[13px] py-4 text-center">{t("loading")}</div>
      ) : mems.length ? (
        mems.map((m) => <MemoryCard key={m.id} m={m} onClick={() => onOpenMemory(m)} />)
      ) : (
        <div className="text-[var(--dim)] text-[13px] py-3">{t("no_entity_memories")}</div>
      )}
    </div>
  );
}
