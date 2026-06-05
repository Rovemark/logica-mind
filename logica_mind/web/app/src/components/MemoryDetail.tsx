import { useEffect, useState } from "react";
import { X, AlignLeft, UserRound, MessagesSquare, Calendar, Plug, Gauge, Tag, Hash, GitBranch } from "lucide-react";
import { api, tShort, type Memory } from "../api";
import { LayerPill, SourceBadge } from "./MemoryCard";
import { useI18n } from "../i18n";

// Obsidian-style note pane: a memory opened as a document — a Properties panel
// (type/agent/session/date/source/tags) over the content, plus its provenance
// ("why do I believe this?" — the source turns it was distilled from).
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

export default function MemoryDetail({ memory, onClose }: { memory: Memory; onClose: () => void }) {
  const { t } = useI18n();
  const [prov, setProv] = useState<{ from: Memory[]; supersedes?: string }>({ from: [] });
  const md = memory.metadata || {};

  useEffect(() => {
    api.provenance(memory.namespace, memory.id).then((d) => setProv({ from: d.from || [], supersedes: d.supersedes }))
      .catch(() => setProv({ from: [] }));
  }, [memory.id, memory.namespace]);

  return (
    <div className="fixed inset-0 z-[55]" onClick={onClose}>
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[1px]" />
      <div onClick={(e) => e.stopPropagation()}
        className="absolute right-0 top-0 bottom-0 w-[560px] max-w-full bg-[var(--bg2)] border-l border-[var(--line)]
          shadow-[var(--shadow)] overflow-y-auto fadein">
        <div className="sticky top-0 bg-[var(--bg2)] border-b border-[var(--line)] px-6 py-3 flex items-center gap-2 z-10">
          <span className="text-[var(--dim2)] text-[12px]">{memory.namespace} / {memory.layer}</span>
          <button onClick={onClose} className="ml-auto text-[var(--dim)] hover:text-[var(--txt)]"><X size={18} /></button>
        </div>

        <div className="px-6 py-5">
          <h1 className="text-[22px] font-bold leading-tight m-0 mb-4 break-words">{memory.content.slice(0, 120)}{memory.content.length > 120 ? "…" : ""}</h1>

          {/* Properties (Obsidian-style) */}
          <div className="text-[var(--dim2)] text-[13px] font-semibold mb-1.5">{t("properties")}</div>
          <div className="border-y border-[var(--line)] py-1.5 mb-5">
            <Prop icon={AlignLeft} k={t("type_word")}><LayerPill layer={memory.layer} /></Prop>
            <Prop icon={UserRound} k={t("prop_agent")}>{memory.namespace}</Prop>
            {md.session && <Prop icon={MessagesSquare} k={t("prop_session")}>{md.session}</Prop>}
            <Prop icon={Calendar} k={t("prop_date")}>{tShort(memory.created_at)}</Prop>
            {md.source && <Prop icon={Plug} k={t("prop_source")}><SourceBadge source={md.source} /></Prop>}
            <Prop icon={Gauge} k={t("prop_importance")}>{(memory.importance ?? 0).toFixed(2)}</Prop>
            {memory.tags && memory.tags.length > 0 && (
              <Prop icon={Tag} k={t("prop_tags")}>{memory.tags.map((tg) => <span key={tg} className="inline-block text-[var(--accent2)] bg-[var(--panel2)] border border-[var(--line)] px-1.5 rounded mr-1 text-[11.5px]">#{tg}</span>)}</Prop>
            )}
            {(md.subject || md.predicate) && (
              <Prop icon={GitBranch} k={t("prop_relation")}><span className="text-[var(--accent2)]">{md.subject} {md.predicate} {md.object}</span></Prop>
            )}
            <Prop icon={Hash} k={t("prop_id")}><span className="text-[var(--dim2)] text-[11px] font-mono">{memory.id}</span></Prop>
          </div>

          {/* Content */}
          <div className="text-[15px] leading-[1.7] whitespace-pre-wrap break-words">{memory.content}</div>

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
              {memory.tags?.includes("distilled") || memory.tags?.includes("inferred")
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
