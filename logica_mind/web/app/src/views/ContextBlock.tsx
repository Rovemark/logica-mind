import { useEffect, useMemo, useState } from "react";
import { Check, Copy, Gauge, Search, SlidersHorizontal } from "lucide-react";
import { api, type ContextResult, type ContextCandidate, type Layer } from "../api";
import { useI18n } from "../i18n";

const LAYER_COLOR: Record<string, string> = {
  episodic: "#7c9cff", semantic: "#4ade80", graph: "#f59e0b", user: "#a78bfa",
};
const BUDGETS = [600, 1200, 2000, 4000];
const fmt = (n: number) => n.toLocaleString("en-US");

// the assembled block is markdown ("## Section" + "- bullet"); split it into
// sections so we can show a per-section token estimate (the "token-efficient" story)
function sections(block: string): { title: string; body: string; tokens: number }[] {
  if (!block.trim()) return [];
  const out: { title: string; body: string; tokens: number }[] = [];
  let cur: { title: string; lines: string[] } | null = null;
  for (const raw of block.split("\n")) {
    const m = raw.match(/^##\s+(.*)$/);
    if (m) { if (cur) out.push(close(cur)); cur = { title: m[1].trim(), lines: [] }; }
    else if (cur) cur.lines.push(raw);
    else { cur = { title: "", lines: [raw] }; }
  }
  if (cur) out.push(close(cur));
  return out;
  function close(c: { title: string; lines: string[] }) {
    const body = c.lines.join("\n").trim();
    return { title: c.title, body, tokens: Math.max(1, Math.round((c.title.length + body.length) / 4)) };
  }
}

export default function ContextBlock({ ns }: { ns: string }) {
  const { t } = useI18n();
  const [query, setQuery] = useState("launch timeline, priorities and who is involved");
  const [budget, setBudget] = useState(1200);
  const [data, setData] = useState<ContextResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let live = true;
    setLoading(true);
    const h = setTimeout(() => {
      api.context(ns, query, budget)
        .then((d) => { if (live) setData(d); })
        .catch(() => { if (live) setData(null); })
        .finally(() => { if (live) setLoading(false); });
    }, 250);
    return () => { live = false; clearTimeout(h); };
  }, [ns, query, budget]);

  const secs = useMemo(() => sections(data?.block || ""), [data?.block]);
  const used = data?.tokens ?? 0;
  const pct = data ? Math.min(100, Math.round((used / Math.max(1, data.budget)) * 100)) : 0;
  const included = data?.candidates.filter((c) => c.included).length ?? 0;

  const copy = () => {
    if (!data?.block) return;
    navigator.clipboard?.writeText(data.block).then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 1400);
    }).catch(() => {});
  };

  return (
    <div className="fadein">
      <div className="flex items-baseline gap-3 mb-1">
        <h2 className="m-0 text-[18px] font-bold tracking-tight">{t("context_block")}</h2>
        <span className="text-[var(--dim2)] text-[12.5px]">{t("context_block_sub")}</span>
      </div>

      {/* query + budget controls */}
      <div className="flex items-center gap-2 flex-wrap mt-3 mb-4">
        <div className="flex items-center gap-2 flex-1 min-w-[240px] card-surface px-3 py-2">
          <Search size={15} className="text-[var(--dim2)] flex-none" />
          <input value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder={t("context_query_ph")}
            className="bg-transparent outline-none border-0 w-full text-[13.5px] text-[var(--txt)] placeholder:text-[var(--dim2)]" />
        </div>
        <div className="flex items-center gap-1.5 card-surface px-2.5 py-2">
          <SlidersHorizontal size={14} className="text-[var(--dim2)]" />
          {BUDGETS.map((b) => (
            <button key={b} onClick={() => setBudget(b)}
              className={`px-2.5 py-1 rounded-lg text-[12px] tabular-nums border ${budget === b
                ? "bg-[var(--panel2)] text-[var(--txt)] border-[var(--line)]"
                : "border-transparent text-[var(--dim)] hover:text-[var(--txt)]"}`}>
              {fmt(b)}
            </button>
          ))}
        </div>
      </div>

      {/* token meter */}
      <div className="card-surface px-4 py-3.5 mb-4">
        <div className="flex items-center gap-2 mb-2">
          <Gauge size={15} className="text-[var(--accent)]" />
          <span className="text-[12.5px] text-[var(--dim)] font-medium">{t("token_budget")}</span>
          <span className="ml-auto text-[13px] tabular-nums">
            <b className="text-[var(--txt)]">{fmt(used)}</b>
            <span className="text-[var(--dim2)]"> / {fmt(data?.budget ?? budget)} {t("tokens_word")}</span>
          </span>
        </div>
        <div className="h-2 rounded-full bg-[var(--panel2)] overflow-hidden">
          <div className="h-full rounded-full transition-[width] duration-300"
            style={{ width: `${pct}%`, background: "linear-gradient(90deg,var(--accent),var(--accent2))" }} />
        </div>
        <div className="flex gap-4 mt-2.5 text-[11.5px] text-[var(--dim2)]">
          <span>{pct}% {t("utilized")}</span>
          <span>{included} / {data?.candidates.length ?? 0} {t("candidates_selected")}</span>
          {data?.namespace && ns === "__all__" && <span>· {data.namespace}</span>}
        </div>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] gap-4 max-[900px]:grid-cols-1">
        {/* left: ranked candidates → which made the cut */}
        <div>
          <div className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px] mb-2.5">{t("ranked_candidates")}</div>
          {loading && !data ? (
            <div className="text-[var(--dim)] card-surface text-center py-8">…</div>
          ) : (data?.candidates.length ? data.candidates.map((c, i) => (
            <Candidate key={i} c={c} rank={i + 1} />
          )) : <div className="text-[var(--dim)] card-surface text-center py-8">{t("no_match")}</div>)}
        </div>

        {/* right: the assembled, prompt-ready block */}
        <div>
          <div className="flex items-center mb-2.5">
            <span className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px]">{t("assembled_block")}</span>
            <button onClick={copy}
              className="ml-auto flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11.5px] border border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)]">
              {copied ? <Check size={12} className="text-[var(--good)]" /> : <Copy size={12} />}
              {copied ? t("copied") : t("copy")}
            </button>
          </div>
          <div className="card-surface overflow-hidden">
            {secs.length ? secs.map((s, i) => (
              <div key={i} className="px-4 py-3 border-b border-[var(--line)] last:border-0">
                {s.title && (
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-[12px] font-bold uppercase tracking-[.6px] text-[var(--accent)]">{s.title}</span>
                    <span className="ml-auto text-[10.5px] tabular-nums text-[var(--dim2)] bg-[var(--panel2)] border border-[var(--line)] px-1.5 py-px rounded-full">
                      ~{fmt(s.tokens)} {t("tokens_word")}
                    </span>
                  </div>
                )}
                <pre className="whitespace-pre-wrap font-sans text-[12.5px] text-[var(--dim)] leading-[1.55] m-0">{s.body}</pre>
              </div>
            )) : <div className="text-[var(--dim)] text-center py-10 text-[13px]">{t("context_empty")}</div>}
          </div>
          <div className="text-[11px] text-[var(--dim2)] mt-2 leading-snug">{t("context_foot")}</div>
        </div>
      </div>
    </div>
  );
}

function Candidate({ c, rank }: { c: ContextCandidate; rank: number }) {
  const layer = (c.memory.layer as Layer) || "episodic";
  const col = LAYER_COLOR[layer] || "#7c9cff";
  return (
    <div className={`card-surface px-3.5 py-2.5 mb-2 border-l-2 ${c.included ? "" : "opacity-55"}`}
      style={{ borderLeftColor: c.included ? "var(--good)" : "var(--line)" }}>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[10.5px] tabular-nums text-[var(--dim2)] w-5">#{rank}</span>
        <span className="text-[10px] px-1.5 py-px rounded-full font-bold uppercase tracking-wide"
          style={{ background: `${col}22`, color: col }}>{layer}</span>
        <span className="text-[11px] tabular-nums text-[var(--dim2)]">{(c.score * 100).toFixed(0)}%</span>
        <span className="ml-auto flex items-center gap-1 text-[10.5px] font-medium"
          style={{ color: c.included ? "var(--good)" : "var(--dim2)" }}>
          {c.included ? <><Check size={11} /> in</> : "—"}
        </span>
      </div>
      <div className="text-[12.5px] text-[var(--txt)] leading-snug">{c.memory.content}</div>
    </div>
  );
}
