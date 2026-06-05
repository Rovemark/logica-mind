import { useEffect, useState } from "react";
import {
  Moon, Layers, Zap, Scissors, GitMerge, Brain, Network,
  AlertTriangle, TrendingDown, ChevronDown, ChevronUp, Activity, Sparkles
} from "lucide-react";
import { api, tShort, type DreamReport, type ContestedPair, type ForgetCurveEntry, type SurpriseEvent } from "../api";
import { useI18n } from "../i18n";

// ---- stat pill at top -------------------------------------------------------
function StatCard({ icon: Icon, value, label, color, sub }: {
  icon: any; value: string | number; label: string; color: string; sub?: string;
}) {
  return (
    <div className="card-surface flex-1 min-w-0 p-4">
      <div className="flex items-center gap-2 mb-1">
        <Icon size={14} style={{ color }} />
        <span className="text-[11px] text-[var(--dim2)] uppercase tracking-[.6px]">{label}</span>
      </div>
      <div className="text-[22px] font-bold tabular-nums" style={{ color }}>{value}</div>
      {sub && <div className="text-[11px] text-[var(--dim2)] mt-0.5">{sub}</div>}
    </div>
  );
}

// ---- forget curve section ---------------------------------------------------
function ForgetCurveSection({ ns }: { ns: string }) {
  const { t } = useI18n();
  const [curve, setCurve] = useState<ForgetCurveEntry[]>([]);
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api.forgetCurve(ns)
      .then(d => { setCurve(d.curve || []); setLoaded(true); setOpen((d.curve || []).length > 0); })
      .catch(() => setLoaded(true));
  }, [ns]);

  const atRisk = curve.filter(e => e.projected_strength_7d < 0.1).length;
  const avgRetention = curve.length
    ? Math.round(curve.reduce((s, e) => s + e.current_retention, 0) / curve.length * 100)
    : null;

  return (
    <div className="card-surface mb-3 overflow-hidden">
      <button onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-2.5 px-4 py-3.5 text-left">
        <TrendingDown size={14} className="text-[var(--gold)] flex-none" />
        <span className="text-[13.5px] font-semibold flex-1">{t("forget_curve")}</span>
        {loaded && (
          <div className="flex items-center gap-2 mr-2">
            {atRisk > 0 && (
              <span className="text-[11px] bg-[#ef444420] text-[#ef4444] border border-[#ef444440] px-2 py-0.5 rounded-full font-medium">
                {atRisk} {t("expiring_word")}
              </span>
            )}
            {avgRetention !== null && (
              <span className="text-[11px] text-[var(--dim2)] tabular-nums">
                {t("avg_word")} {avgRetention}%
              </span>
            )}
            {curve.length > 0 && (
              <span className="text-[11px] text-[var(--dim2)]">{curve.length}</span>
            )}
          </div>
        )}
        {open ? <ChevronUp size={13} className="text-[var(--dim)] flex-none" />
               : <ChevronDown size={13} className="text-[var(--dim)] flex-none" />}
      </button>

      {open && (
        <div className="px-4 pb-4">
          {!loaded || curve.length === 0 ? (
            <div className="text-[var(--dim)] text-[12.5px] py-4">{t("no_beliefs_at_risk")}</div>
          ) : (
            <div className="flex flex-col">
              {curve.slice(0, 12).map((e, i) => {
                const pct = Math.round(e.current_retention * 100);
                const danger = pct < 20;
                const warn   = pct < 50;
                const barColor = danger ? "#ef4444" : warn ? "var(--gold)" : "var(--accent)";
                return (
                  <div key={i} className="py-4 border-b border-[var(--line)] last:border-0">
                    {/* content */}
                    <div className="text-[13px] text-[var(--txt)] leading-snug mb-3 line-clamp-2">{e.content}</div>

                    {/* progress bar */}
                    <div className="h-[5px] rounded-full bg-[var(--panel2)] overflow-hidden mb-2.5">
                      <div className="h-full rounded-full transition-all"
                        style={{ width: `${pct}%`, background: barColor }} />
                    </div>

                    {/* stats row */}
                    <div className="flex items-center gap-4 text-[11.5px]">
                      <span className="font-semibold tabular-nums" style={{ color: barColor }}>
                        {t("retention")} {pct}%
                      </span>
                      <span className="text-[var(--dim2)] tabular-nums">
                        {t("projected")} <b className="text-[var(--dim)]">{Math.round(e.projected_strength_7d * 100) / 100}</b>
                      </span>
                      <span className="text-[var(--dim2)] tabular-nums ml-auto">
                        {e.days_since_recall}d {t("days_since")}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---- contested beliefs section ----------------------------------------------
function ContestedSection({ ns }: { ns: string }) {
  const { t } = useI18n();
  const [pairs, setPairs] = useState<ContestedPair[]>([]);
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api.contested(ns)
      .then(d => { setPairs(d.contested || []); setLoaded(true); })
      .catch(() => setLoaded(true));
  }, [ns]);

  return (
    <div className="card-surface mb-3 overflow-hidden">
      <button onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-2.5 px-4 py-3.5 text-left">
        <AlertTriangle size={14} className="text-[#fb7185] flex-none" />
        <span className="text-[13.5px] font-semibold flex-1">{t("contested_beliefs")}</span>
        {loaded && (
          <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium mr-2 flex-none
            ${pairs.length > 0
              ? "bg-[#fb718520] text-[#fb7185] border border-[#fb718540]"
              : "text-[var(--dim2)]"}`}>
            {pairs.length}
          </span>
        )}
        {open ? <ChevronUp size={13} className="text-[var(--dim)] flex-none" />
               : <ChevronDown size={13} className="text-[var(--dim)] flex-none" />}
      </button>

      {open && (
        <div className="px-4 pb-4">
          {pairs.length === 0 ? (
            <div className="text-[var(--dim)] text-[12.5px] py-4">{t("no_contested")}</div>
          ) : pairs.map((p, i) => (
            <div key={i} className="py-4 border-b border-[var(--line)] last:border-0">
              {/* current belief */}
              <div className="flex items-start gap-2.5 mb-3">
                <div className="w-2 h-2 rounded-full bg-[var(--accent)] flex-none mt-[5px]" />
                <div className="text-[13px] text-[var(--txt)] flex-1 leading-snug">{p.current.content}</div>
                <span className="text-[12px] font-semibold text-[var(--accent)] flex-none tabular-nums">
                  {Math.round(p.confidence_new * 100)}%
                </span>
              </div>
              {/* superseded belief */}
              <div className="flex items-start gap-2.5">
                <div className="w-2 h-2 rounded-full border border-[var(--dim2)] flex-none mt-[5px]" />
                <div className="text-[12.5px] text-[var(--dim2)] line-through flex-1 leading-snug">{p.superseded.content}</div>
                <span className="text-[11.5px] text-[var(--dim2)] flex-none tabular-nums">
                  {Math.round(p.confidence_old * 100)}%
                </span>
              </div>
              {p.surprise_score > 0.1 && (
                <div className="mt-2 flex items-center gap-1.5 text-[11.5px] text-[#fb7185]">
                  <Activity size={11} />
                  {t("surprise_score")} {p.surprise_score.toFixed(2)}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---- surprise events section ------------------------------------------------
function SurprisesSection({ ns }: { ns: string }) {
  const { t } = useI18n();
  const [events, setEvents] = useState<SurpriseEvent[]>([]);
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api.surprises(ns)
      .then(d => { setEvents(d.surprises || []); setLoaded(true); })
      .catch(() => setLoaded(true));
  }, [ns]);

  return (
    <div className="card-surface mb-3 overflow-hidden">
      <button onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-2.5 px-4 py-3.5 text-left">
        <Sparkles size={14} className="text-[#a78bfa] flex-none" />
        <span className="text-[13.5px] font-semibold flex-1">{t("surprise_score")}</span>
        {loaded && (
          <span className={`text-[11px] px-2 py-0.5 rounded-full font-medium mr-2 flex-none
            ${events.length > 0 ? "bg-[#a78bfa20] text-[#a78bfa] border border-[#a78bfa40]" : "text-[var(--dim2)]"}`}>
            {events.length}
          </span>
        )}
        {open ? <ChevronUp size={13} className="text-[var(--dim)] flex-none" />
               : <ChevronDown size={13} className="text-[var(--dim)] flex-none" />}
      </button>
      {open && (
        <div className="px-4 pb-4">
          {events.length === 0 ? (
            <div className="text-[var(--dim)] text-[12.5px] py-3">—</div>
          ) : events.map((e, i) => (
            <div key={i} className="py-3 border-b border-[var(--line)] last:border-0 flex items-start gap-2.5">
              <Sparkles size={11} className="text-[#a78bfa] flex-none mt-1" />
              <div className="flex-1 min-w-0">
                <div className="text-[13px] text-[var(--txt)] leading-snug">{e.content}</div>
                <div className="text-[10px] text-[var(--dim2)] mt-0.5">{tShort(e.created_at)?.slice(0, 10)}</div>
              </div>
              <span className="text-[12px] font-semibold text-[#a78bfa] flex-none tabular-nums">
                {(e.surprise_score ?? 0).toFixed(2)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---- dream cycle card -------------------------------------------------------
function DreamCard({ report }: { report: DreamReport }) {
  const { t } = useI18n();
  const total = report.distilled + report.reinforced + report.forgotten + report.derived + report.inferred + report.graph_edges;

  const stats: { icon: any; label: string; value: number; color: string }[] = [
    { icon: Layers,    label: t("distilled"),    value: report.distilled,    color: "var(--accent)" },
    { icon: Zap,       label: t("reinforced"),   value: report.reinforced,   color: "var(--gold)" },
    { icon: Scissors,  label: t("forgotten"),    value: report.forgotten,    color: "var(--dim)" },
    { icon: GitMerge,  label: t("derived"),      value: report.derived,      color: "var(--accent2)" },
    { icon: Network,   label: t("inferred"),     value: report.inferred,     color: "#a78bfa" },
    { icon: Network,   label: t("graph_edges"),  value: report.graph_edges,  color: "var(--accent2)" },
  ].filter(s => s.value > 0);

  return (
    <div className="card-surface mb-2.5">
      <div className="flex items-center gap-2 mb-3">
        <Moon size={13} className="text-[var(--accent2)]" />
        <span className="text-[12px] text-[var(--dim2)] tabular-nums">{tShort(report.timestamp)}</span>
        {report.namespace && (
          <span className="text-[11px] bg-[var(--panel2)] border border-[var(--line)] px-1.5 rounded text-[var(--dim2)]">
            {report.namespace}
          </span>
        )}
        <span className="ml-auto text-[11.5px] font-semibold text-[var(--txt)] tabular-nums">{total} {t("ops_word")}</span>
      </div>

      {stats.length > 0 ? (
        <div className="grid grid-cols-2 gap-1.5 max-[600px]:grid-cols-1">
          {stats.map((s, i) => (
            <div key={i} className="flex items-center gap-2 bg-[var(--panel2)] border border-[var(--line)] rounded-[8px] px-3 py-2">
              <s.icon size={12} style={{ color: s.color }} className="flex-none" />
              <span className="text-[12px] text-[var(--dim)] flex-1 truncate">{s.label}</span>
              <span className="text-[13px] font-semibold tabular-nums" style={{ color: s.color }}>{s.value}</span>
            </div>
          ))}
          {report.user_synthesized && (
            <div className="flex items-center gap-2 bg-[var(--panel2)] border border-[var(--line)] rounded-[8px] px-3 py-2">
              <Brain size={12} className="text-[var(--accent)] flex-none" />
              <span className="text-[12px] text-[var(--dim)] flex-1">{t("user_synthesized")}</span>
              <span className="text-[12px] text-[var(--accent)]">✓</span>
            </div>
          )}
        </div>
      ) : (
        <div className="text-[var(--dim2)] text-[12px]">{t("dream_noop")}</div>
      )}
    </div>
  );
}

// ---- main view --------------------------------------------------------------
export default function Dreams({ ns }: { ns: string }) {
  const { t } = useI18n();
  const [dreams, setDreams] = useState<DreamReport[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api.dreams(ns).then(d => { setDreams(d.dreams || []); setLoaded(true); }).catch(() => setLoaded(true));
  }, [ns]);

  const totalOps  = dreams.reduce((a, r) => a + r.distilled + r.reinforced + r.forgotten + r.derived + r.inferred, 0);
  const totalForgotten = dreams.reduce((a, r) => a + r.forgotten, 0);
  const totalDistilled = dreams.reduce((a, r) => a + r.distilled, 0);

  return (
    <div className="fadein">
      <div className="flex items-center gap-3 mb-5">
        <h2 className="m-0 text-[18px] font-bold tracking-tight">{t("dream_journal")}</h2>
        {dreams.length > 0 && (
          <span className="text-[var(--dim2)] text-[12px]">{dreams.length} {t("dream_cycle").toLowerCase()}s</span>
        )}
      </div>

      {/* summary strip — always visible */}
      {loaded && (
        <div className="flex gap-3 mb-4 flex-wrap max-[640px]:grid max-[640px]:grid-cols-2">
          <StatCard icon={Moon}     value={dreams.length}    label={t("dream_cycle") + "s"} color="var(--accent2)"  />
          <StatCard icon={Layers}   value={totalDistilled}   label={t("distilled")}          color="var(--accent)"   />
          <StatCard icon={Scissors} value={totalForgotten}   label={t("forgotten")}          color="var(--dim)"      />
          <StatCard icon={Activity} value={totalOps}         label={t("total_ops")}          color="var(--gold)"     />
        </div>
      )}

      {/* always-visible moat sections */}
      <ForgetCurveSection ns={ns} />
      <ContestedSection   ns={ns} />
      <SurprisesSection   ns={ns} />

      {/* dream cycles */}
      <div className="text-[var(--dim2)] text-[11px] uppercase tracking-[.7px] mb-3 mt-4">
        {t("dream_journal")} · {t("dream_cycle")}s
      </div>
      {!loaded ? (
        <div className="card-surface text-center py-10 text-[var(--dim)]">{t("loading")}</div>
      ) : dreams.length === 0 ? (
        <div className="card-surface py-10 text-center">
          <Moon size={28} className="text-[var(--dim2)] mx-auto mb-3" />
          <div className="text-[var(--txt)] text-[14px] font-medium mb-1">{t("no_dreams")}</div>
          <div className="text-[var(--dim)] text-[12.5px]">
            <code className="bg-[var(--panel2)] border border-[var(--line)] rounded px-1.5 py-0.5">mind.dream()</code>
          </div>
        </div>
      ) : dreams.map((r, i) => <DreamCard key={i} report={r} />)}
    </div>
  );
}
