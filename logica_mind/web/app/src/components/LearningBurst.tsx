import { useEffect, useState } from "react";
import { Brain, Check, Database, Link2, RefreshCw, Search, Sparkles, UserRound } from "lucide-react";
import type { AddResult } from "../api";
import { useI18n } from "../i18n";

const LAYER_COLOR: Record<string, string> = {
  episodic: "#7c9cff", semantic: "#4ade80", graph: "#f59e0b", user: "#a78bfa",
};

// The "learn" animation: after you add text, show exactly what the engine did
// with it — extracted facts revealed one by one (Mem0-style "memory n/n"), with
// updates that supersede a prior belief, new graph links, and dedup/no-op.
export default function LearningBurst({ input, result, onDone }: {
  input: string; result: AddResult; onDone: () => void;
}) {
  const { t } = useI18n();
  const items = result.created || [];
  const total = items.length;
  // reveal timeline: chips first (staggered), then the pipeline stages tick in
  const stageCount = 3 + (result.graph_edges > 0 ? 1 : 0) + (result.user_updated ? 1 : 0);
  const steps = total + stageCount;
  const [revealed, setRevealed] = useState(0);

  useEffect(() => {
    if (revealed >= steps) return;
    const h = setTimeout(() => setRevealed((r) => r + 1), revealed === 0 ? 350 : 460);
    return () => clearTimeout(h);
  }, [revealed, steps]);

  const chipsShown = Math.min(revealed, total);
  const done = revealed >= steps;

  const stages = [
    { icon: Sparkles, label: t("learn_extracted", { n: String(total || 1) }) },
    { icon: Search, label: t("learn_resolved") },
    { icon: Database, label: t("learn_stored") },
    ...(result.graph_edges > 0 ? [{ icon: Link2, label: t("learn_linked", { n: String(result.graph_edges) }) }] : []),
    ...(result.user_updated ? [{ icon: UserRound, label: t("learn_user") }] : []),
  ];

  return (
    <div className="fadein">
      {/* header */}
      <div className="flex items-center gap-2.5 mb-3">
        <div className="w-[30px] h-[30px] rounded-[9px] grid place-items-center text-white bg-gradient-to-br from-[var(--accent)] to-[var(--accent2)]">
          {done ? <Check size={16} /> : <Brain size={16} className="animate-pulse" />}
        </div>
        <div>
          <div className="text-[14px] font-bold">{done ? t("learned") : t("learning")}</div>
          <div className="text-[11px] text-[var(--dim2)] tabular-nums">
            {result.deduped
              ? t("learn_known")
              : done
                ? t("learn_done", { n: String(total) })
                : t("learn_updating", { i: String(chipsShown), n: String(total) })}
          </div>
        </div>
      </div>

      {/* the input, as a bubble */}
      <div className="rounded-[12px] bg-[var(--panel2)] border border-[var(--line)] px-3.5 py-2.5 mb-3 text-[12.5px] text-[var(--dim)] leading-snug">
        {input}
      </div>

      {/* extracted facts → chips, revealed one by one */}
      {result.deduped ? (
        <div className="flex items-center gap-2 text-[12.5px] text-[var(--dim)] card-surface px-3.5 py-3 mb-3">
          <RefreshCw size={14} className="text-[var(--gold)]" /> {t("learn_known_desc")}
        </div>
      ) : (
        <div className="flex flex-col gap-2 mb-3">
          {items.map((it, i) => {
            const col = LAYER_COLOR[it.layer] || "#7c9cff";
            const on = chipsShown > i;
            return (
              <div key={i}
                style={{ opacity: on ? 1 : 0, transform: on ? "none" : "translateY(8px)", transition: "all .38s cubic-bezier(.2,.7,.2,1)" }}
                className="card-surface px-3.5 py-2.5">
                <div className="flex items-center gap-2">
                  <span className="grid place-items-center w-[18px] h-[18px] rounded-full" style={{ background: `${col}22` }}>
                    <Check size={12} style={{ color: col }} />
                  </span>
                  <span className="text-[10px] px-1.5 py-px rounded-full font-bold uppercase tracking-wide flex-none"
                    style={{ background: `${col}1f`, color: col }}>{it.layer}</span>
                  {it.category && <span className="text-[10.5px] text-[var(--dim2)]">{it.category}</span>}
                  <span className={`ml-auto text-[9.5px] font-bold uppercase tracking-wide px-1.5 py-px rounded-full flex-none ${
                    it.op === "updated" ? "text-[var(--gold)] bg-[var(--gold)]/15" : "text-[var(--good)] bg-[var(--good)]/15"}`}>
                    {it.op === "updated" ? t("op_updated") : t("op_new")}
                  </span>
                </div>
                <div className="text-[13px] text-[var(--txt)] leading-snug mt-1.5">{it.content}</div>
                {it.superseded && (
                  <div className="text-[11px] text-[var(--dim2)] mt-1 flex items-center gap-1.5">
                    <span className="text-[var(--dim2)]">{t("op_was")}</span>
                    <span className="line-through decoration-[var(--warn)]/70">{it.superseded}</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* pipeline stages, ticking in after the chips */}
      <div className="flex flex-wrap gap-1.5 mb-4">
        {stages.map((s, i) => {
          const on = revealed > total + i;
          const Icon = s.icon;
          return (
            <span key={i}
              style={{ opacity: on ? 1 : 0.28, transition: "opacity .3s" }}
              className="flex items-center gap-1.5 text-[11px] px-2 py-1 rounded-full bg-[var(--panel2)] border border-[var(--line)] text-[var(--dim)]">
              {on ? <Check size={11} className="text-[var(--good)]" /> : <Icon size={11} />} {s.label}
            </span>
          );
        })}
      </div>

      <button onClick={onDone}
        className="w-full px-4 py-2 rounded-[9px] text-[13px] font-semibold text-white bg-gradient-to-br from-[var(--accent)] to-[var(--accent2)]">
        {t("done")}
      </button>
    </div>
  );
}
