import { useEffect, useState } from "react";
import { Database, Network, GitBranch, Users, MessagesSquare, AlertTriangle, Gauge, Activity, ShieldCheck } from "lucide-react";
import { api, tShort, type AnalyticsData } from "../api";
import Pager, { paginate } from "../components/Pager";
import { useI18n } from "../i18n";
import { useNav } from "../navctx";

const RANGES: [string, number][] = [["7d", 7], ["30d", 30], ["90d", 90]];

// namespaces are free-form; we classify each by a light naming convention
// (kind:name) so the lake reads like a typed catalog — defaults to AGENT.
const TYPE_COLOR: Record<string, string> = { USER: "#a78bfa", ORG: "#22d3ee", DOMAIN: "#f59e0b", AGENT: "#7c9cff" };
function nsType(name: string): string {
  const n = name.toLowerCase();
  if (n.startsWith("user:") || n === "user" || n.includes("profile")) return "USER";
  if (n.startsWith("org:") || n.includes("company") || n.includes("acme")) return "ORG";
  if (n.startsWith("domain:") || n.includes("docs") || n.includes("kb")) return "DOMAIN";
  return "AGENT";
}

const LAYER_COLOR: Record<string, string> = {
  episodic: "var(--gold)", semantic: "var(--accent)", graph: "#a78bfa", user: "#4ade80",
};
const SRC_COLOR = ["#7c9cff", "#4ade80", "#f59e0b", "#a78bfa", "#f472b6", "#22d3ee"];

// ---- stat card ----
function Stat({ icon: Icon, label, value, color = "var(--accent)", sub }:
  { icon: any; label: string; value: string | number; color?: string; sub?: string }) {
  return (
    <div className="card-surface px-4 py-3.5 min-w-0">
      <div className="flex items-center gap-1.5 mb-1.5">
        <Icon size={13} style={{ color }} className="flex-none" />
        <span className="text-[10px] text-[var(--dim2)] uppercase tracking-[.6px] truncate">{label}</span>
      </div>
      <div className="text-[22px] font-bold tabular-nums leading-none" style={{ color }}>{value}</div>
      {sub && <div className="text-[10.5px] text-[var(--dim2)] mt-1">{sub}</div>}
    </div>
  );
}

// ---- vertical bars over time ----
function TimeBars({ data, title, sub }: { data: { date: string; count: number }[]; title: string; sub?: string }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  const total = data.reduce((a, d) => a + d.count, 0);
  return (
    <div className="card-surface p-4">
      <div className="flex items-baseline gap-2 mb-0.5">
        <span className="text-[13px] font-semibold">{title}</span>
        <span className="ml-auto text-[11px] text-[var(--dim2)] tabular-nums">{total}</span>
      </div>
      {sub && <div className="text-[11px] text-[var(--dim2)] mb-3">{sub}</div>}
      <div className="flex items-end gap-[3px] h-[120px]">
        {data.map((d, i) => (
          <div key={i} title={`${d.date.slice(5)} · ${d.count}`}
            className="flex-1 rounded-t-[3px] bg-gradient-to-t from-[var(--accent)]/55 to-[var(--accent)] hover:to-[var(--accent2)] transition-colors min-h-[2px]"
            style={{ height: `${Math.max(2, (d.count / max) * 100)}%` }} />
        ))}
      </div>
      <div className="flex justify-between text-[10px] text-[var(--dim2)] mt-1.5">
        <span>{data[0]?.date.slice(5)}</span><span>{data[data.length - 1]?.date.slice(5)}</span>
      </div>
    </div>
  );
}

// ---- horizontal bars (distribution) ----
function HBars({ rows, title }: { rows: { label: string; value: number; color: string }[]; title: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="card-surface p-4">
      <div className="text-[13px] font-semibold mb-3">{title}</div>
      <div className="flex flex-col gap-2.5">
        {rows.length === 0 && <div className="text-[var(--dim)] text-[12px] py-6 text-center">—</div>}
        {rows.map((r, i) => (
          <div key={i}>
            <div className="flex items-center gap-2 text-[12px] mb-1">
              <span className="w-2 h-2 rounded-full flex-none" style={{ background: r.color }} />
              <span className="text-[var(--dim)] truncate">{r.label}</span>
              <span className="ml-auto tabular-nums font-semibold text-[var(--txt)]">{r.value}</span>
            </div>
            <div className="h-[6px] rounded-full bg-[var(--panel2)] overflow-hidden">
              <div className="h-full rounded-full transition-all" style={{ width: `${(r.value / max) * 100}%`, background: r.color }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- inline sparkline (svg) ----
function Spark({ values, color = "var(--accent2)" }: { values: number[]; color?: string }) {
  const max = Math.max(1, ...values);
  const w = 92, h = 22, n = values.length;
  const bw = w / n;
  return (
    <svg width={w} height={h} className="block">
      {values.map((v, i) => {
        const bh = Math.max(1, (v / max) * (h - 2));
        return <rect key={i} x={i * bw + 0.5} y={h - bh} width={bw - 1.2} height={bh} rx={1}
          fill={color} opacity={v ? 0.85 : 0.18} />;
      })}
    </svg>
  );
}

export default function Analytics({ ns, colorFor }: { ns: string; colorFor: (n: string) => string }) {
  const { t } = useI18n();
  const { onNs } = useNav();
  const [d, setD] = useState<AnalyticsData | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [range, setRange] = useState(30);
  const [lpage, setLpage] = useState(1);

  useEffect(() => {
    setLoaded(false);
    api.analytics(ns, range).then((r) => { setD(r); setLoaded(true); }).catch(() => setLoaded(true));
  }, [ns, range]);

  if (!loaded) return <div className="fadein text-[var(--dim)] py-16 text-center">{t("loading")}</div>;
  if (!d) return <div className="fadein text-[var(--dim)] py-16 text-center">{t("nothing_here")}</div>;

  const tot = d.totals;
  const layerRows = ["episodic", "semantic", "graph", "user"]
    .map((l) => ({ label: t(`layer_${l}` as any), value: tot[l] || 0, color: LAYER_COLOR[l] }));
  const sourceRows = d.by_source.map((s, i) => ({ label: s.source, value: s.count, color: SRC_COLOR[i % SRC_COLOR.length] }));
  const agentRows = d.by_namespace.slice(0, 8).map((r) => ({ label: r.namespace, value: r.total, color: colorFor(r.namespace) }));
  const lake = paginate(d.by_namespace, lpage, 12);

  return (
    <div className="fadein">
      <div className="flex items-baseline gap-3 mb-4">
        <h2 className="m-0 text-[18px] font-bold tracking-tight">{t("analytics")}</h2>
        <span className="text-[var(--dim2)] text-[12px] max-[680px]:hidden">{t("analytics_sub")}</span>
        <div className="ml-auto flex gap-1">
          {RANGES.map(([l, dval]) => (
            <button key={l} onClick={() => setRange(dval)}
              className={`px-2.5 py-1 rounded-lg border text-[12px] tabular-nums ${range === dval ? "bg-[var(--panel2)] text-[var(--txt)] border-[var(--line)]" : "border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)]"}`}>{l}</button>
          ))}
          <button onClick={() => setRange(0)}
            className={`px-2.5 py-1 rounded-lg border text-[12px] ${range === 0 ? "bg-[var(--panel2)] text-[var(--txt)] border-[var(--line)]" : "border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)]"}`}>{t("all_word")}</button>
        </div>
      </div>

      {/* stat strip */}
      <div className="grid gap-2.5 mb-3" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(112px,1fr))" }}>
        <Stat icon={Database} label={t("memories")} value={tot.memories ?? 0} color="var(--accent)" />
        <Stat icon={Users} label={t("agents_clones")} value={tot.namespaces ?? 0} color="var(--accent2)" />
        <Stat icon={Network} label={t("graph_entities")} value={tot.entities ?? 0} color="#a78bfa" />
        <Stat icon={GitBranch} label={t("relations")} value={tot.relations ?? 0} color="#a78bfa" />
        <Stat icon={MessagesSquare} label={t("sessions")} value={tot.sessions ?? 0} color="var(--gold)" />
        <Stat icon={AlertTriangle} label={t("contradictions").split(" ")[0]} value={tot.contradictions ?? 0} color="#fb7185" />
        <Stat icon={Gauge} label={t("avg_latency")} value={`${d.ops.avg_latency_ms}ms`} color="var(--accent)" sub={`${d.ops.requests} ${t("requests_word")}`} />
        <Stat icon={Activity} label={t("error_rate")} value={`${d.ops.error_rate}%`} color={d.ops.error_rate > 1 ? "#fb7185" : "#4ade80"} />
      </div>

      {/* 2x2 chart grid */}
      <div className="grid grid-cols-2 gap-2.5 mb-3 max-[760px]:grid-cols-1">
        <TimeBars data={d.timeseries} title={t("memories_over_time")} sub={range === 0 ? t("all_time") : t("last_n_days", { n: String(range) })} />
        <HBars rows={layerRows} title={t("by_layer")} />
        <HBars rows={sourceRows} title={t("by_source")} />
        <HBars rows={agentRows} title={t("by_agent")} />
      </div>

      {/* Context-lake-style table */}
      <div className="card-surface overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--line)] flex items-center gap-2">
          <span className="text-[12px] font-semibold">{t("memory_lake")}</span>
          <span className="ml-auto text-[11px] text-[var(--dim2)] tabular-nums">{tot.memories} {t("memories_word")}</span>
        </div>
        <div className="grid grid-cols-[1fr_72px_72px_72px_110px_84px] gap-2 px-4 py-2 text-[10px] uppercase tracking-[.6px] text-[var(--dim2)] border-b border-[var(--line)] max-[680px]:grid-cols-[1fr_60px_92px]">
          <span>{t("lake_subject")}</span>
          <span className="text-right max-[680px]:hidden">{t("lake_entities")}</span>
          <span className="text-right">{t("lake_facts")}</span>
          <span className="text-right max-[680px]:hidden">{t("relations")}</span>
          <span className="max-[680px]:hidden">{t("lake_activity")}</span>
          <span className="text-right max-[680px]:hidden">{t("lake_updated")}</span>
        </div>
        {lake.slice.map((r) => (
          <div key={r.namespace} onClick={() => onNs(r.namespace)} title={r.namespace}
            className="grid grid-cols-[1fr_72px_72px_72px_110px_84px] gap-2 px-4 py-2.5 items-center border-b border-[var(--line)] last:border-0 hover:bg-[var(--panel2)] cursor-pointer max-[680px]:grid-cols-[1fr_60px_92px]">
            <span className="flex items-center gap-2 min-w-0">
              <span className="w-2 h-2 rounded-full flex-none" style={{ background: colorFor(r.namespace) }} />
              <span className="font-semibold text-[13px] truncate">{r.namespace}</span>
              {(() => { const ty = nsType(r.namespace), c = TYPE_COLOR[ty]; return (
                <span className="text-[9px] font-bold tracking-wide px-1.5 py-px rounded-full flex-none"
                  style={{ background: `${c}1f`, color: c }}>{ty}</span>
              ); })()}
            </span>
            <span className="text-right tabular-nums text-[12.5px] text-[var(--dim)] max-[680px]:hidden">{r.entities}</span>
            <span className="text-right tabular-nums text-[12.5px] text-[var(--dim)]">{r.facts}</span>
            <span className="text-right tabular-nums text-[12.5px] text-[var(--dim)] max-[680px]:hidden">{r.relations}</span>
            <span className="max-[680px]:hidden"><Spark values={r.spark} color={colorFor(r.namespace)} /></span>
            <span className="text-right text-[11px] text-[var(--dim2)] tabular-nums max-[680px]:hidden">{tShort(r.last)?.slice(0, 10)}</span>
          </div>
        ))}
        {lake.pages > 1 && <div className="px-4 pb-2"><Pager page={lake.page} pages={lake.pages} onPage={setLpage} /></div>}
        {/* governance footer — the real guarantees every row carries */}
        <div className="px-4 py-2.5 border-t border-[var(--line)] flex items-center gap-1.5 flex-wrap">
          <ShieldCheck size={12} className="text-[var(--good)] flex-none" />
          {["gov_provenance", "gov_sourced", "gov_versioned", "gov_erase"].map((k) => (
            <span key={k} className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-[var(--panel2)] border border-[var(--line)] text-[var(--dim)]">{t(k)}</span>
          ))}
          <span className="text-[10.5px] text-[var(--dim2)] ml-1 max-[680px]:hidden">{t("gov_note")}</span>
        </div>
      </div>
    </div>
  );
}
