import { useEffect, useMemo, useRef, useState } from "react";
import { Hexagon, Clock, Timer, RotateCw, Maximize2, Palette, X, Search, SlidersHorizontal, Check } from "lucide-react";
import { api, tShort, type GraphData } from "../api";
import GraphCanvas, { type GraphHandle } from "../components/GraphCanvas";
import NodeDetail from "../components/NodeDetail";
import { useI18n } from "../i18n";
import { AREAS, dimArea, dimColor, type Area } from "../lifearea";

type ColorBy = "namespace" | "community" | "area" | "centrality";

// predicate-class palette — must match the canvas edge grammar (PCLASS_RGB)
const PCLASS_HEX: Record<string, string> = {
  social: "#f59e0b", has: "#4ade80", causal: "#fb7185",
  locative: "#22d3ee", temporal: "#a78bfa", is_a: "#7c9cff", other: "#94a3b8",
};
// node tint for the Centrality colour mode: cool (low) → hot (high)
const centColor = (c: number) => `hsl(${Math.round(210 - 210 * Math.min(1, Math.max(0, c)))},72%,55%)`;

export default function GraphView({ ns, colorFor, onOpenMemory, focusEntity }: { ns: string; colorFor: (n: string) => string; onOpenMemory?: (m: any) => void; focusEntity?: { name: string; n: number } | null }) {
  const { t } = useI18n();
  const [data, setData] = useState<GraphData>({ nodes: [], links: [] });
  const [history, setHistory] = useState(true);
  const [colorBy, setColorBy] = useState<ColorBy>("namespace");
  const [coMention, setCoMention] = useState(true);
  const [areaFilter, setAreaFilter] = useState<Area | null>(null);
  const [minConf, setMinConf] = useState(0);
  const [predOff, setPredOff] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [at, setAt] = useState<string | null>(null);
  const [range, setRange] = useState<{ min: string; max: string } | null>(null);
  const [scrub, setScrub] = useState(false);
  const [showLegend, setShowLegend] = useState(false);
  const [colorMenu, setColorMenu] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const gref = useRef<GraphHandle>(null);

  useEffect(() => {
    const layers = coMention ? ["relation", "co_mention"] : ["relation"];
    api.graph(ns, history, at, { layers }).then(setData).catch(() => setData({ nodes: [], links: [] }));
  }, [ns, history, at, coMention]);

  // reset transient view state when switching namespace
  useEffect(() => { setPicked(null); setScrub(false); setAt(null); setAreaFilter(null); setQuery(""); setPredOff(new Set()); setMinConf(0); }, [ns]);

  // open an entity's detail when navigated here from a backlink (Connected panel)
  useEffect(() => { if (focusEntity?.name) { setPicked(focusEntity.name); gref.current?.center(focusEntity.name); } }, [focusEntity?.n, focusEntity?.name]);

  const areasPresent = useMemo(() => {
    const s = new Set<Area>();
    data.nodes.forEach((n) => { if (n.dimension) s.add(dimArea(n.dimension)); });
    return s;
  }, [data]);
  const hasAreas = areasPresent.size > 0;

  // predicate classes actually present (for the relation-type filter)
  const predsPresent = useMemo(() => {
    const s = new Set<string>();
    data.links.forEach((l) => { if ((l.kind || "relation") === "relation" && l.pclass) s.add(l.pclass); });
    return [...s];
  }, [data]);

  // apply the filters: life-area subset (drops nodes), then per-link min-confidence
  // + relation-type (drops links only, so node positions stay put)
  const shown: GraphData = useMemo(() => {
    let nodes = data.nodes, links = data.links;
    if (colorBy === "area" && areaFilter) {
      const keep = new Set(nodes.filter((n) => n.dimension && dimArea(n.dimension) === areaFilter).map((n) => n.id));
      nodes = nodes.filter((n) => keep.has(n.id));
      links = links.filter((l) => keep.has(l.source) && keep.has(l.target));
    }
    links = links.filter((l) => {
      if ((l.kind || "relation") !== "relation") return true;       // only relations carry confidence/pclass
      if (minConf > 0 && (l.confidence ?? 1) < minConf) return false;
      if (predOff.size && l.pclass && predOff.has(l.pclass)) return false;
      return true;
    });
    return { nodes, links };
  }, [data, colorBy, areaFilter, minConf, predOff]);

  const tint = colorBy === "area" ? (n: any) => (n.dimension ? dimColor(n.dimension) : "var(--dim2)")
    : colorBy === "centrality" ? (n: any) => centColor(n.centrality || 0)
    : undefined;
  const communities = colorBy === "community";

  async function toggleScrub() {
    if (scrub) { setScrub(false); setAt(null); return; }
    const tr = await api.timerange(ns);
    if (!tr.max || !tr.min) return;
    setRange({ min: tr.min, max: tr.max }); setScrub(true);
  }

  function runSearch(q: string) {
    const s = q.trim().toLowerCase();
    if (!s) return;
    const hit = shown.nodes.find((n) => n.id.toLowerCase() === s)
      || shown.nodes.find((n) => n.id.toLowerCase().includes(s));
    if (hit) { setPicked(hit.id); gref.current?.center(hit.id); }
  }

  const Btn = ({ on, onClick, icon: Icon, children }: any) => (
    <button onClick={onClick}
      className={`glass border rounded-[9px] px-3 py-[7px] text-[12px] inline-flex items-center gap-1.5
        ${on ? "text-[var(--gold)] border-[var(--gold)]" : "text-[var(--dim)] border-[var(--line)] hover:text-[var(--txt)]"}`}>
      <Icon size={13} /> {children}
    </button>
  );

  const COLOR_OPTS: { id: ColorBy; key: string; disabled?: boolean }[] = [
    { id: "namespace", key: "graph_color_namespace" },
    { id: "community", key: "graph_color_community" },
    { id: "area", key: "graph_color_area", disabled: !hasAreas },
    { id: "centrality", key: "graph_color_centrality" },
  ];
  const legendNs = useMemo(() => {
    const s = new Set<string>();
    shown.nodes.forEach((n) => (n.namespaces || []).forEach((x) => s.add(x)));
    return [...s].slice(0, 8);
  }, [shown]);
  const nFilters = (minConf > 0 ? 1 : 0) + predOff.size;

  return (
    <div className="fadein">
      <h2 className="m-0 mb-4 text-[18px] font-bold tracking-tight">{t("graph")}</h2>
      <div className="relative" style={{ height: "calc(100vh - 200px)", minHeight: 420 }}>
        <div className="absolute top-3 left-3.5 text-[var(--dim2)] text-[11.5px] z-[3]">
          {shown.nodes.length} {t("graph_entities")} · {shown.links.length} {t("relations")}
          {at && <span className="text-[var(--gold)]"> · {t("graph_as_of")} {tShort(at)}</span>}
        </div>

        {/* ── top filter bar ── */}
        <div className="absolute top-3 right-3 flex gap-1.5 z-[4] flex-wrap justify-end max-w-[78%]">
          {/* search / focus */}
          <div className="glass border border-[var(--line)] rounded-[9px] px-2 flex items-center gap-1.5 text-[12px]">
            <Search size={12} className="text-[var(--dim2)]" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && runSearch(query)}
              placeholder={t("graph_search")} className="bg-transparent outline-none w-[120px] py-[7px] text-[var(--txt)]" />
          </div>
          {/* colour-by */}
          <div className="relative">
            <Btn on={colorMenu || colorBy !== "namespace"} onClick={() => setColorMenu((v) => !v)} icon={Palette}>
              {t(("graph_color_" + colorBy) as any)}
            </Btn>
            {colorMenu && (
              <div className="absolute right-0 mt-1 glass border border-[var(--line)] rounded-[11px] p-1.5 w-[170px] shadow-[var(--shadow)]">
                <div className="text-[var(--dim2)] text-[10px] uppercase tracking-[.6px] px-2 py-1">{t("graph_color_by")}</div>
                {COLOR_OPTS.map((o) => (
                  <button key={o.id} disabled={o.disabled} onClick={() => { setColorBy(o.id); setColorMenu(false); if (o.id !== "area") setAreaFilter(null); }}
                    className={`w-full text-left px-2 py-1.5 rounded-lg text-[12.5px] flex items-center gap-2 disabled:opacity-30
                      ${colorBy === o.id ? "bg-[var(--panel2)] text-[var(--txt)]" : "text-[var(--dim)] hover:text-[var(--txt)] hover:bg-[var(--panel2)]"}`}>
                    {colorBy === o.id ? <Check size={13} /> : <span className="w-[13px]" />}{t(o.key as any)}
                  </button>
                ))}
              </div>
            )}
          </div>
          {/* connection layers */}
          <Btn on={coMention} onClick={() => setCoMention((v) => !v)} icon={Hexagon}>{t("glayer_comention")}</Btn>
          {/* filters popover */}
          <div className="relative">
            <Btn on={filtersOpen || nFilters > 0} onClick={() => setFiltersOpen((v) => !v)} icon={SlidersHorizontal}>
              {t("graph_filters")}{nFilters > 0 ? ` ·${nFilters}` : ""}
            </Btn>
            {filtersOpen && (
              <div className="absolute right-0 mt-1 glass border border-[var(--line)] rounded-[12px] p-3 w-[248px] shadow-[var(--shadow)]">
                <div className="flex items-center mb-2">
                  <span className="text-[var(--dim2)] text-[10px] uppercase tracking-[.6px]">{t("graph_filters")}</span>
                  {nFilters > 0 && <button onClick={() => { setMinConf(0); setPredOff(new Set()); }} className="ml-auto text-[11px] text-[var(--accent)] hover:underline">{t("graph_reset")}</button>}
                </div>
                <div className="text-[11.5px] text-[var(--dim)] flex items-center justify-between mb-1">
                  <span>{t("graph_min_conf")}</span><span className="tabular-nums text-[var(--txt)]">{Math.round(minConf * 100)}%</span>
                </div>
                <input type="range" min={0} max={1} step={0.05} value={minConf} onChange={(e) => setMinConf(+e.target.value)} className="w-full accent-[var(--accent)] mb-3" />
                {predsPresent.length > 0 && <>
                  <div className="text-[11.5px] text-[var(--dim)] mb-1.5">{t("graph_predicates")}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {predsPresent.map((p) => {
                      const off = predOff.has(p);
                      return (
                        <button key={p} onClick={() => setPredOff((s) => { const n = new Set(s); off ? n.delete(p) : n.add(p); return n; })}
                          className="text-[11px] px-2 py-1 rounded-full border inline-flex items-center gap-1.5"
                          style={{ borderColor: off ? "var(--line)" : PCLASS_HEX[p], color: off ? "var(--dim2)" : PCLASS_HEX[p], opacity: off ? 0.5 : 1 }}>
                          <span className="w-2 h-2 rounded-full" style={{ background: PCLASS_HEX[p] }} />{p}
                        </button>
                      );
                    })}
                  </div>
                </>}
              </div>
            )}
          </div>
          <Btn on={history} onClick={() => setHistory((v) => !v)} icon={Clock}>{t("graph_history")}</Btn>
          <Btn on={scrub} onClick={toggleScrub} icon={Timer}>{t("graph_time")}</Btn>
          <Btn onClick={() => gref.current?.reheat()} icon={RotateCw}>{t("graph_shake")}</Btn>
          <Btn onClick={() => gref.current?.fit()} icon={Maximize2}>{t("graph_fit")}</Btn>
        </div>

        {/* life-area filter chips — only in the Life-area colour mode */}
        {colorBy === "area" && hasAreas && (
          <div className="absolute top-[52px] right-3 flex gap-1.5 z-[3] flex-wrap justify-end max-w-[78%]">
            {AREAS.filter((a) => areasPresent.has(a.id)).map((a) => {
              const on = areaFilter === a.id;
              return (
                <button key={a.id} onClick={() => setAreaFilter(on ? null : a.id)}
                  className="glass border rounded-full px-2.5 py-[5px] text-[11px] inline-flex items-center gap-1.5"
                  style={{ borderColor: on ? a.color : "var(--line)", color: on ? a.color : "var(--dim)", background: on ? `${a.color}1a` : undefined }}>
                  <span className="w-2 h-2 rounded-full" style={{ background: a.color }} /> {a.label}
                </button>
              );
            })}
          </div>
        )}

        {shown.nodes.length === 0 ? (
          <div className="w-full h-full grid place-items-center text-[var(--dim)] card-surface">{t("graph_empty")}</div>
        ) : (
          <GraphCanvas ref={gref} data={shown} communities={communities} colorFor={colorFor} onPick={setPicked} nodeTint={tint} />
        )}

        {picked && (
          <NodeDetail ns={ns} name={picked} onClose={() => setPicked(null)}
            onOpenMemory={(m) => onOpenMemory?.(m)} onPickEntity={(n) => setPicked(n)} />
        )}

        {/* legend — adapts to the active colour mode */}
        {!scrub && shown.nodes.length > 0 && (
          <div className="absolute bottom-3 left-3.5 z-[3]">
            {showLegend ? (
              <div className="glass border border-[var(--line)] rounded-[12px] p-3 text-[11.5px] w-[230px] max-h-[280px] overflow-y-auto shadow-[var(--shadow)]">
                <div className="flex items-center mb-2">
                  <span className="text-[var(--dim2)] text-[10px] uppercase tracking-[.7px]">{t("graph_legend")}</span>
                  <button onClick={() => setShowLegend(false)} className="ml-auto text-[var(--dim)] hover:text-[var(--txt)]"><X size={13} /></button>
                </div>
                {colorBy === "community" ? (
                  <div className="flex items-center gap-1.5 text-[var(--dim)]"><Hexagon size={12} /> {t("colored_by_community")}</div>
                ) : colorBy === "centrality" ? (
                  <div className="flex flex-col gap-1.5">
                    <div className="text-[var(--dim2)] text-[10px] mb-0.5">{t("colored_by_centrality")}</div>
                    <div className="h-2 rounded-full" style={{ background: "linear-gradient(90deg, hsl(210,72%,55%), hsl(120,72%,55%), hsl(40,72%,55%), hsl(0,72%,55%))" }} />
                    <div className="flex justify-between text-[10px] text-[var(--dim2)]"><span>low</span><span>hub</span></div>
                  </div>
                ) : colorBy === "area" ? (
                  <div className="flex flex-col gap-1.5">
                    <div className="text-[var(--dim2)] text-[10px] mb-0.5">{t("graph_colored_by_area")}</div>
                    {AREAS.filter((a) => areasPresent.has(a.id)).map((a) => (
                      <span key={a.id} className="inline-flex items-center gap-2 text-[var(--dim)]">
                        <span className="w-2.5 h-2.5 rounded-full flex-none" style={{ background: a.color }} /> {a.label}
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className="flex flex-col gap-1.5">
                    {legendNs.map((n) => (
                      <span key={n} className="inline-flex items-center gap-2 text-[var(--dim)]">
                        <span className="w-2.5 h-2.5 rounded-full flex-none" style={{ background: colorFor(n) }} />
                        <span className="truncate">{n}</span>
                      </span>
                    ))}
                    <span className="inline-flex items-center gap-2 text-[var(--dim)] mt-1"><span className="w-2.5 h-2.5 rounded-full bg-[var(--gold)] flex-none" />{t("shared_entity")}</span>
                  </div>
                )}
                {/* edge grammar key — always shown */}
                <div className="border-t border-[var(--line)] mt-2.5 pt-2 flex flex-col gap-1">
                  <div className="text-[var(--dim2)] text-[10px] mb-0.5">{t("graph_predicates")}</div>
                  {predsPresent.map((p) => (
                    <span key={p} className="inline-flex items-center gap-2 text-[var(--dim)]"><span className="w-3 border-t-2 flex-none" style={{ borderColor: PCLASS_HEX[p] }} />{p}</span>
                  ))}
                  {coMention && <span className="inline-flex items-center gap-2 text-[var(--dim)]"><span className="w-3 border-t border-dashed flex-none" style={{ borderColor: "#7888aa" }} />{t("glayer_comention")}</span>}
                  <span className="inline-flex items-center gap-2 text-[var(--dim)]"><span className="w-3 border-t border-dashed border-[var(--dim2)] flex-none" />{t("superseded")}</span>
                </div>
              </div>
            ) : (
              <button onClick={() => setShowLegend(true)}
                className="glass border border-[var(--line)] rounded-[9px] px-2.5 py-[7px] text-[12px] text-[var(--dim)] hover:text-[var(--txt)] inline-flex items-center gap-1.5">
                <Palette size={13} /> {t("graph_legend")}
              </button>
            )}
          </div>
        )}

        {scrub && range && (
          <div className="absolute left-3.5 right-3.5 bottom-3 glass border border-[var(--line)] rounded-[11px] px-3.5 py-2.5 flex items-center gap-3.5 z-[3]">
            <span className="text-[11.5px] text-[var(--dim)] tabular-nums whitespace-nowrap">{tShort(range.min)}</span>
            <input type="range" className="flex-1 accent-[var(--accent)]"
              min={Date.parse(range.min.replace(" ", "T"))} max={Date.parse(range.max.replace(" ", "T"))} step={1000}
              defaultValue={Date.parse(range.max.replace(" ", "T"))}
              onChange={(e) => setAt(new Date(+e.target.value).toISOString().replace(/\.\d+Z$/, "Z"))} />
            <span className="text-[11.5px] text-[var(--dim)] whitespace-nowrap">
              {t("graph_as_of")}: <span className="text-[var(--gold)] font-semibold">{at ? tShort(at) : tShort(range.max)}</span>
            </span>
          </div>
        )}
      </div>
      <div className="text-[var(--dim2)] text-[12px] mt-2.5 max-[820px]:hidden">
        {t("graph_tip")}
      </div>
    </div>
  );
}
