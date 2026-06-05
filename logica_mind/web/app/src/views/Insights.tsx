import { useEffect, useState } from "react";
import { AlertCircle, ChevronDown, ChevronUp } from "lucide-react";
import { api, type Community } from "../api";
import InsightList from "../components/InsightList";
import { useI18n } from "../i18n";

interface StaleItem { id: string; content: string; age_days: number; confidence: number; }

export default function Insights({ ns }: { ns: string }) {
  const { t } = useI18n();
  const [insight, setInsight] = useState("");
  const [comms, setComms] = useState<Community[]>([]);
  const [stale, setStale] = useState<StaleItem[]>([]);
  const [staleOpen, setStaleOpen] = useState(false);

  useEffect(() => {
    api.reflect(ns).then((d) => setInsight(d.insight || "")).catch(() => setInsight(""));
    api.communities(ns).then((d) => setComms(d.communities || [])).catch(() => setComms([]));
    api.staleBeliefs(ns).then((d) => setStale(d.stale || [])).catch(() => setStale([]));
  }, [ns]);

  return (
    <div className="fadein">
      <h2 className="m-0 mb-4 text-[18px] font-bold tracking-tight">{t("insights")}</h2>

      {/* stale beliefs — epistemic self-doubt */}
      <div className="card-surface mb-4 overflow-hidden">
        <button onClick={() => setStaleOpen(v => !v)}
          className="w-full flex items-center gap-2.5 px-4 py-3.5 text-left">
          <AlertCircle size={14} className="text-[var(--gold)] flex-none" />
          <span className="text-[13.5px] font-semibold flex-1">{t("stale_beliefs")}</span>
          {stale.length > 0 && (
            <span className="text-[11px] bg-[var(--gold)]/20 text-[var(--gold)] border border-[var(--gold)]/40 px-2 py-0.5 rounded-full font-medium mr-2">
              {stale.length}
            </span>
          )}
          {staleOpen ? <ChevronUp size={13} className="text-[var(--dim)] flex-none" />
                     : <ChevronDown size={13} className="text-[var(--dim)] flex-none" />}
        </button>
        {staleOpen && (
          <div className="px-4 pb-4">
            <div className="text-[11.5px] text-[var(--dim2)] mb-3">{t("stale_desc")}</div>
            {stale.length === 0 ? (
              <div className="text-[var(--dim)] text-[12.5px]">{t("no_stale")}</div>
            ) : stale.map((s, i) => (
              <div key={i} className="py-3 border-b border-[var(--line)] last:border-0">
                <div className="text-[13px] text-[var(--txt)] mb-1.5 leading-snug">{s.content}</div>
                <div className="flex gap-4 text-[11.5px] text-[var(--dim2)]">
                  <span>{s.age_days}d {t("age_days")}</span>
                  <span>{t("confidence")}: <b className="text-[var(--gold)]">{Math.round(s.confidence * 100)}%</b></span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* reflect */}
      <div className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px] mb-2.5">{t("whats_notable")}</div>
      {insight ? <InsightList text={insight} />
        : <div className="text-[var(--dim)] text-center py-8">{t("not_enough_reflect")}</div>}

      {/* communities */}
      <div className="h-[22px]" />
      <div className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px] mb-2.5">
        {t("knowledge_communities")} · {comms.length}
      </div>
      {comms.length ? comms.map((c, i) => (
        <div key={i} className="card-surface px-[15px] py-[13px] mb-2.5">
          <div className="flex items-center gap-[9px] mb-1.5">
            <span className="bg-graph text-[10px] px-2 py-[2px] rounded-full font-bold uppercase tracking-wide">
              {t("cluster_word")} {i + 1}
            </span>
            <span className="text-[11px] text-[var(--dim)] bg-[var(--panel2)] border border-[var(--line)] px-2 py-[1px] rounded-full">
              {c.size} {t("graph_entities")}
            </span>
          </div>
          <div className="text-[var(--dim)] text-[13px]">{c.nodes.slice(0, 10).join(" · ")}</div>
          {c.facts.length > 0 && (
            <div className="text-[var(--dim2)] text-[12px] mt-2">
              {c.facts.slice(0, 4).map((f, k) => <div key={k}>• {f}</div>)}
            </div>
          )}
        </div>
      )) : <div className="text-[var(--dim)] text-center py-8">{t("no_graph")}</div>}
    </div>
  );
}
