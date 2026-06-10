import { useEffect, useMemo, useRef, useState } from "react";
import { Hexagon, Clock, Timer, RotateCw, Maximize2, Palette, X, Search, SlidersHorizontal, Check, Route, ArrowRight, Lightbulb, Spline, Orbit } from "lucide-react";
import { api, tShort, valueColor, type GraphData, type PathResult, type SuggestedLink } from "../api";
import GraphCanvas, { type GraphHandle } from "../components/GraphCanvas";
import NodeDetail from "../components/NodeDetail";
import { useI18n } from "../i18n";
import { AREAS, dimArea, type Area } from "../lifearea";
import { predLabel } from "../predlabel";

type ColorBy = "namespace" | "community" | "area" | "type" | "channel" | "centrality";
// graph ORGANISATION (layout engine): organic web · facet orbits (hubs with their
// members around them — the org-map look) · concentric rings by importance.
type LayoutMode = "force" | "orbit" | "rings";
const LAYOUTS: LayoutMode[] = ["force", "orbit", "rings"];

// predicate-class palette — must match the canvas edge grammar (PCLASS_RGB)
const PCLASS_HEX: Record<string, string> = {
  social: "#f59e0b", has: "#4ade80", causal: "#fb7185",
  locative: "#22d3ee", temporal: "#a78bfa", is_a: "#7c9cff", other: "#94a3b8",
};
// node tint for the Centrality colour mode: cool (low) → hot (high)
const centColor = (c: number) => `hsl(${Math.round(210 - 210 * Math.min(1, Math.max(0, c)))},72%,55%)`;
// human-readable label for a dimension id (strip the area prefix, spaces for _)
const dimLabel = (d: string) => d.replace(/^(biz|project|org)_/, "").replace(/_/g, " ");

export default function GraphView({ ns, colorFor, onOpenMemory, focusEntity }: { ns: string; colorFor: (n: string) => string; onOpenMemory?: (m: any) => void; focusEntity?: { name: string; n: number } | null }) {
  const { t } = useI18n();
  const [data, setData] = useState<GraphData>({ nodes: [], links: [] });
  const [loaded, setLoaded] = useState(false);       // first load done (gates the full-screen spinner)
  const [refetching, setRefetching] = useState(false); // a toggle is reloading — keep the graph visible
  const [showOrphans, setShowOrphans] = useState(false); // Obsidian-style: hide link-less nodes by default
  const reqRef = useRef(0);                           // stale-guard: ignore out-of-order responses
  const [history, setHistory] = useState(true);
  const [colorBy, setColorBy] = useState<ColorBy>("area");   // colour by life-area when available (multi-colour + meaningful); falls back to namespace if the data has no dimensions
  // layout/organisation mode — persisted so the user's preferred view sticks
  const [layout, setLayout] = useState<LayoutMode>(() => {
    const v = localStorage.getItem("graph_layout") as LayoutMode | null;
    return v && LAYOUTS.includes(v) ? v : "force";
  });
  const [layoutMenu, setLayoutMenu] = useState(false);
  useEffect(() => { localStorage.setItem("graph_layout", layout); }, [layout]);
  const [coMention, setCoMention] = useState(true);
  const [semantic, setSemantic] = useState(false);
  const [suggest, setSuggest] = useState(false);
  const [suggestedLinks, setSuggestedLinks] = useState<SuggestedLink[]>([]);
  const [tintQuery, setTintQuery] = useState("");
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
  const [focusNode, setFocusNode] = useState<string | null>(null);   // local/ego graph
  const [depth, setDepth] = useState(2);
  const [hover, setHover] = useState<{ id: string; x: number; y: number } | null>(null);
  const [hoverInfo, setHoverInfo] = useState<{ name: string; type: string; mems: any[] } | null>(null);
  const [pathOpen, setPathOpen] = useState(false);
  const [pathFrom, setPathFrom] = useState("");
  const [pathTo, setPathTo] = useState("");
  const [pathRes, setPathRes] = useState<PathResult | null>(null);
  const hoverCache = useRef<Record<string, { name: string; type: string; mems: any[] }>>({});
  const wrapRef = useRef<HTMLDivElement>(null);
  const gref = useRef<GraphHandle>(null);

  useEffect(() => {
    const layers = ["relation", coMention && "co_mention", semantic && "semantic"].filter(Boolean) as string[];
    // Don't blank the canvas on every toggle — keep the current graph on screen and
    // show a small "updating" pill instead. The stale-guard (rid) ensures only the
    // latest request wins, so a slow layer fetch can never leave it stuck loading.
    const rid = ++reqRef.current;
    setRefetching(true);
    api.graph(ns, history, at, { layers, focus: focusNode || undefined, depth })
      .then((d) => { if (rid === reqRef.current) { setData(d); setLoaded(true); } })
      .catch(() => { if (rid === reqRef.current) { setData({ nodes: [], links: [] }); setLoaded(true); } })
      .finally(() => { if (rid === reqRef.current) setRefetching(false); });
  }, [ns, history, at, coMention, semantic, focusNode, depth]);

  // reset transient view state when switching namespace
  useEffect(() => { setPicked(null); setScrub(false); setAt(null); setAreaFilter(null); setQuery(""); setPredOff(new Set()); setMinConf(0); setFocusNode(null); setPathRes(null); }, [ns]);

  // suggested links (predicted-but-missing edges) — opt-in overlay
  useEffect(() => {
    if (!suggest) { setSuggestedLinks([]); return; }
    api.suggested(ns).then((d) => setSuggestedLinks(d.suggested || [])).catch(() => setSuggestedLinks([]));
  }, [suggest, ns]);

  // hover preview: fetch (and cache) the hovered entity's top facts
  useEffect(() => {
    if (!hover) { setHoverInfo(null); return; }
    const id = hover.id, cached = hoverCache.current[id];
    if (cached) { setHoverInfo(cached); return; }
    let alive = true;
    const nodeType = data.nodes.find((n) => n.id === id)?.type || "";
    // preview=true → fast path (top mentioning memories only, no heavy graph scan)
    api.node(ns, id, true).then((d) => { if (!alive) return; const info = { name: id, type: nodeType || d.type || "", mems: (d.memories || []).slice(0, 3) }; hoverCache.current[id] = info; setHoverInfo(info); }).catch(() => {});
    return () => { alive = false; };
  }, [hover?.id, ns]);

  // open an entity's detail when navigated here from a backlink (Connected panel)
  useEffect(() => { if (focusEntity?.name) { setPicked(focusEntity.name); gref.current?.center(focusEntity.name); } }, [focusEntity?.n, focusEntity?.name]);

  const areasPresent = useMemo(() => {
    const s = new Set<Area>();
    data.nodes.forEach((n) => { if (n.dimension) s.add(dimArea(n.dimension)); });
    return s;
  }, [data]);
  const hasAreas = areasPresent.size > 0;
  // distinct dimensions present, grouped by life-area — each dimension now gets its
  // OWN colour (34 of them), not just the 4 area buckets, so the legend mirrors that
  const dimsByArea = useMemo(() => {
    const by: Record<string, string[]> = {}; const seen = new Set<string>();
    data.nodes.forEach((n) => { if (n.dimension && !seen.has(n.dimension)) { seen.add(n.dimension); (by[dimArea(n.dimension)] ||= []).push(n.dimension); } });
    for (const k in by) by[k].sort();
    return by;
  }, [data]);
  // entity types present (Concept/Product/Person/Organization/Place/Project) — covers
  // ALL graph nodes (unlike dimensions, which only the semantic layer carries)
  const typesPresent = useMemo(() => {
    const s = new Set<string>(); data.nodes.forEach((n) => { if (n.type) s.add(n.type); });
    return [...s].sort();
  }, [data]);
  const hasTypes = typesPresent.length > 0;
  // channels present (whatsapp/telegram/voice/sessions/… — whatever the host app tags)
  const channelsPresent = useMemo(() => {
    const s = new Set<string>(); data.nodes.forEach((n) => { if (n.channel) s.add(n.channel); });
    return [...s].sort();
  }, [data]);
  const hasChannels = channelsPresent.length > 0;
  // default is "area" (colourful + meaningful); if this dataset has no life-areas
  // yet, fall back to namespace colouring so it isn't an all-grey graph.
  useEffect(() => { if (loaded && !hasAreas && colorBy === "area") setColorBy("namespace"); }, [loaded, hasAreas]);

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
    // localize the predicate shown on each edge (display-only; pclass logic uses the raw value)
    links = links.map((l) => (l.label ? { ...l, label: predLabel(l.label, t) } : l));
    // overlay predicted-but-missing edges (only between nodes already shown)
    if (suggest && suggestedLinks.length) {
      const ids = new Set(nodes.map((n) => n.id));
      for (const s of suggestedLinks) if (ids.has(s.a) && ids.has(s.b)) links.push({ source: s.a, target: s.b, label: "", kind: "suggested", weight: s.score });
    }
    // Órfãos toggle (Obsidian-style): hide nodes with no visible edge unless asked.
    // Computed over the FINAL link set, so it respects layer/confidence/type filters.
    if (!showOrphans) {
      const deg = new Set<string>();
      for (const l of links) { deg.add(l.source); deg.add(l.target); }
      nodes = nodes.filter((n) => deg.has(n.id));
    }
    return { nodes, links };
  }, [data, colorBy, areaFilter, minConf, predOff, t, suggest, suggestedLinks, showOrphans]);

  // how many link-less nodes the graph currently holds (for the toggle's count badge)
  const orphanCount = useMemo(() => {
    const deg = new Set<string>();
    for (const l of data.links) { deg.add(l.source); deg.add(l.target); }
    return data.nodes.reduce((c, n) => c + (deg.has(n.id) ? 0 : 1), 0);
  }, [data]);

  // a highlight query paints matches gold and dims the rest (Obsidian colour groups);
  // otherwise colour follows the colour-by mode
  const tq = tintQuery.trim().toLowerCase();
  // memoised so its identity is stable across re-renders (hover/state churn) — the
  // canvas keys a repaint on nodeTint identity, so an unstable closure would defeat
  // idle-suspend by repainting on every render.
  const tint = useMemo(() => tq ? (n: any) => (n.id.toLowerCase().includes(tq) ? "#fbbf24" : "var(--dim2)")
    : colorBy === "area" ? (n: any) => (n.dimension ? valueColor(n.dimension) : "var(--dim2)")
    : colorBy === "type" ? (n: any) => valueColor(n.type)
    : colorBy === "channel" ? (n: any) => (n.channel ? valueColor(n.channel) : "var(--dim2)")
    : colorBy === "centrality" ? (n: any) => centColor(n.centrality || 0)
    : undefined, [tq, colorBy]);
  const communities = colorBy === "community" && !tq;
  // facet→group mapping for the orbit/rings layouts: hubs/sectors follow the ACTIVE
  // colour facet — "colour by agent" + orbit = one orbit per agent, by type = one per
  // entity type, by life-area = one per dimension. Community grouping is resolved
  // inside the canvas (it owns the connected components).
  const groupOf = useMemo(() => {
    if (colorBy === "area") return (n: any) => (n.dimension ? dimLabel(n.dimension) : null);
    if (colorBy === "type") return (n: any) => n.type || null;
    if (colorBy === "channel") return (n: any) => n.channel || null;
    if (colorBy === "community") return undefined;
    return (n: any) => (n.namespaces && n.namespaces[0]) || null;
  }, [colorBy]);

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

  async function runPath() {
    if (!pathFrom.trim() || !pathTo.trim()) return;
    try { setPathRes(await api.path(ns, pathFrom.trim(), pathTo.trim())); } catch { setPathRes(null); }
  }
  const pathIds = pathRes?.found ? pathRes.path : undefined;

  const Btn = ({ on, onClick, icon: Icon, children, title }: any) => (
    <button onClick={onClick} title={title}
      className={`glass border rounded-[9px] px-3 py-[7px] text-[12px] inline-flex items-center gap-1.5
        ${on ? "text-[var(--gold)] border-[var(--gold)]" : "text-[var(--dim)] border-[var(--line)] hover:text-[var(--txt)]"}`}>
      <Icon size={13} /> {children}
    </button>
  );

  const COLOR_OPTS: { id: ColorBy; key: string; disabled?: boolean }[] = [
    { id: "namespace", key: "graph_color_namespace" },
    { id: "community", key: "graph_color_community" },
    { id: "area", key: "graph_color_area", disabled: !hasAreas },
    { id: "type", key: "graph_color_type", disabled: !hasTypes },
    { id: "channel", key: "graph_color_channel", disabled: !hasChannels },
    { id: "centrality", key: "graph_color_centrality" },
  ];
  const legendNs = useMemo(() => {
    const s = new Set<string>();
    shown.nodes.forEach((n) => (n.namespaces || []).forEach((x) => s.add(x)));
    return [...s].slice(0, 8);
  }, [shown]);
  const nFilters = (minConf > 0 ? 1 : 0) + predOff.size + (tq ? 1 : 0);

  return (
    <div className="fadein">
      <h2 className="m-0 mb-4 text-[18px] font-bold tracking-tight">{t("graph")}</h2>
      <div ref={wrapRef} className="relative" style={{ height: "calc(100vh - 200px)", minHeight: 420 }}>
        <div className="absolute top-3 left-3.5 text-[var(--dim2)] text-[11.5px] z-[3]">
          {shown.nodes.length} {t("graph_entities")} · {shown.links.length} {t("relations")}
          {at && <span className="text-[var(--gold)]"> · {t("graph_as_of")} {tShort(at)}</span>}
          {refetching && <span className="text-[var(--accent)]"> · {t("graph_updating")}</span>}
        </div>

        {/* local/ego-graph banner — appears when focused on one entity */}
        {focusNode && (
          <div className="absolute top-[34px] left-3.5 z-[4] glass border border-[var(--accent)]/50 rounded-[10px] px-3 py-1.5 flex items-center gap-2.5 text-[12px]">
            <span className="text-[var(--accent)] font-semibold">{t("graph_local")}:</span>
            <span className="text-[var(--txt)] max-w-[150px] truncate">{focusNode}</span>
            <span className="text-[var(--dim2)]">·</span>
            <span className="text-[var(--dim)]">{t("graph_depth")}</span>
            <input type="range" min={1} max={3} step={1} value={depth} onChange={(e) => setDepth(+e.target.value)} className="w-[70px] accent-[var(--accent)]" />
            <span className="tabular-nums text-[var(--txt)] w-2">{depth}</span>
            <button onClick={() => setFocusNode(null)} title={t("graph_exit_local")} className="text-[var(--dim)] hover:text-[var(--warn)]"><X size={13} /></button>
          </div>
        )}

        {/* ── top filter bar ── */}
        <div className="absolute top-3 right-3 flex gap-1.5 z-[4] flex-wrap justify-end max-w-[78%]">
          {/* search / focus */}
          <div className="glass border border-[var(--line)] rounded-[9px] px-2 flex items-center gap-1.5 text-[12px]" title={t("tip_search")}>
            <Search size={12} className="text-[var(--dim2)]" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && runSearch(query)}
              placeholder={t("graph_search")} className="bg-transparent outline-none w-[120px] py-[7px] text-[var(--txt)]" />
          </div>
          {/* layout / organisation */}
          <div className="relative">
            <Btn on={layoutMenu || layout !== "force"} onClick={() => setLayoutMenu((v) => !v)} icon={Orbit} title={t("tip_layout")}>
              {t(("graph_layout_" + layout) as any)}
            </Btn>
            {layoutMenu && (
              <div className="absolute right-0 mt-1 glass border border-[var(--line)] rounded-[11px] p-1.5 w-[170px] shadow-[var(--shadow)]">
                <div className="text-[var(--dim2)] text-[10px] uppercase tracking-[.6px] px-2 py-1">{t("graph_layout_by")}</div>
                {LAYOUTS.map((m) => (
                  <button key={m} onClick={() => { setLayout(m); setLayoutMenu(false); }}
                    className={`w-full text-left px-2 py-1.5 rounded-lg text-[12.5px] flex items-center gap-2
                      ${layout === m ? "bg-[var(--panel2)] text-[var(--txt)]" : "text-[var(--dim)] hover:text-[var(--txt)] hover:bg-[var(--panel2)]"}`}>
                    {layout === m ? <Check size={13} /> : <span className="w-[13px]" />}{t(("graph_layout_" + m) as any)}
                  </button>
                ))}
              </div>
            )}
          </div>
          {/* colour-by */}
          <div className="relative">
            <Btn on={colorMenu || colorBy !== "namespace"} onClick={() => setColorMenu((v) => !v)} icon={Palette} title={t("tip_colour")}>
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
          <Btn on={coMention} onClick={() => setCoMention((v) => !v)} icon={Hexagon} title={t("tip_comention")}>{t("glayer_comention")}</Btn>
          <Btn on={semantic} onClick={() => setSemantic((v) => !v)} icon={Spline} title={t("tip_semantic")}>{t("glayer_semantic")}</Btn>
          <Btn on={suggest} onClick={() => setSuggest((v) => !v)} icon={Lightbulb} title={t("tip_suggested")}>{t("glayer_suggested")}</Btn>
          {/* filters popover */}
          <div className="relative">
            <Btn on={filtersOpen || nFilters > 0} onClick={() => setFiltersOpen((v) => !v)} icon={SlidersHorizontal} title={t("tip_filters")}>
              {t("graph_filters")}{nFilters > 0 ? ` ·${nFilters}` : ""}
            </Btn>
            {filtersOpen && (
              <div className="absolute right-0 mt-1 glass border border-[var(--line)] rounded-[12px] p-3 w-[248px] shadow-[var(--shadow)]">
                <div className="flex items-center mb-2">
                  <span className="text-[var(--dim2)] text-[10px] uppercase tracking-[.6px]">{t("graph_filters")}</span>
                  {nFilters > 0 && <button onClick={() => { setMinConf(0); setPredOff(new Set()); setTintQuery(""); }} className="ml-auto text-[11px] text-[var(--accent)] hover:underline">{t("graph_reset")}</button>}
                </div>
                {/* Órfãos — show/hide link-less nodes (Obsidian-style toggle) */}
                <div onClick={() => setShowOrphans((v) => !v)} className="flex items-center justify-between mb-3 cursor-pointer select-none">
                  <span className="text-[11.5px] text-[var(--dim)]">{t("graph_orphans")}{orphanCount > 0 ? ` ·${orphanCount}` : ""}</span>
                  <span role="switch" aria-checked={showOrphans}
                    className={`relative w-9 h-[18px] rounded-full transition-colors flex-none ${showOrphans ? "bg-[var(--accent)]" : "bg-[var(--line)]"}`}>
                    <span className={`absolute top-[2px] h-3.5 w-3.5 rounded-full bg-white transition-all ${showOrphans ? "left-[19px]" : "left-[2px]"}`} />
                  </span>
                </div>
                <div className="text-[11.5px] text-[var(--dim)] flex items-center justify-between mb-1">
                  <span>{t("graph_min_conf")}</span><span className="tabular-nums text-[var(--txt)]">{Math.round(minConf * 100)}%</span>
                </div>
                <input type="range" min={0} max={1} step={0.05} value={minConf} onChange={(e) => setMinConf(+e.target.value)} className="w-full accent-[var(--accent)] mb-3" />
                <div className="text-[11.5px] text-[var(--dim)] mb-1.5">{t("graph_highlight")}</div>
                <input value={tintQuery} onChange={(e) => setTintQuery(e.target.value)} placeholder="…"
                  className="w-full bg-[var(--panel2)] border border-[var(--line)] rounded-[8px] px-2 py-1.5 text-[12px] text-[var(--txt)] outline-none focus:border-[var(--accent)]/60 mb-3" />
                {predsPresent.length > 0 && <>
                  <div className="text-[11.5px] text-[var(--dim)] mb-1.5">{t("graph_predicates")}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {predsPresent.map((p) => {
                      const off = predOff.has(p);
                      return (
                        <button key={p} onClick={() => setPredOff((s) => { const n = new Set(s); off ? n.delete(p) : n.add(p); return n; })}
                          className="text-[11px] px-2 py-1 rounded-full border inline-flex items-center gap-1.5"
                          style={{ borderColor: off ? "var(--line)" : PCLASS_HEX[p], color: off ? "var(--dim2)" : PCLASS_HEX[p], opacity: off ? 0.5 : 1 }}>
                          <span className="w-2 h-2 rounded-full" style={{ background: PCLASS_HEX[p] }} />{t(("pclass_" + p) as any)}
                        </button>
                      );
                    })}
                  </div>
                </>}
              </div>
            )}
          </div>
          <Btn on={pathOpen || !!pathIds} onClick={() => { setPathOpen((v) => !v); if (pathOpen) setPathRes(null); }} icon={Route} title={t("tip_path")}>{t("graph_path")}</Btn>
          <Btn on={history} onClick={() => setHistory((v) => !v)} icon={Clock} title={t("tip_history")}>{t("graph_history")}</Btn>
          <Btn on={scrub} onClick={toggleScrub} icon={Timer} title={t("tip_time")}>{t("graph_time")}</Btn>
          <Btn onClick={() => gref.current?.reheat()} icon={RotateCw} title={t("tip_shake")}>{t("graph_shake")}</Btn>
          <Btn onClick={() => gref.current?.fit()} icon={Maximize2} title={t("tip_fit")}>{t("graph_fit")}</Btn>
        </div>

        {/* Path mode — "how is A related to B?" */}
        {pathOpen && (
          <div className="absolute top-[34px] left-3.5 z-[4] glass border border-[var(--line)] rounded-[12px] p-3 w-[320px] shadow-[var(--shadow)]">
            <div className="text-[var(--dim2)] text-[10px] uppercase tracking-[.6px] mb-2 flex items-center gap-1.5"><Route size={12} /> {t("graph_path_hint")}</div>
            <div className="flex items-center gap-1.5 mb-2">
              <input value={pathFrom} onChange={(e) => setPathFrom(e.target.value)} onKeyDown={(e) => e.key === "Enter" && runPath()}
                placeholder={t("graph_path_from")} className="flex-1 min-w-0 bg-[var(--panel2)] border border-[var(--line)] rounded-[8px] px-2 py-1.5 text-[12px] text-[var(--txt)] outline-none focus:border-[var(--accent)]/60" />
              <ArrowRight size={13} className="text-[var(--dim2)] flex-none" />
              <input value={pathTo} onChange={(e) => setPathTo(e.target.value)} onKeyDown={(e) => e.key === "Enter" && runPath()}
                placeholder={t("graph_path_to")} className="flex-1 min-w-0 bg-[var(--panel2)] border border-[var(--line)] rounded-[8px] px-2 py-1.5 text-[12px] text-[var(--txt)] outline-none focus:border-[var(--accent)]/60" />
            </div>
            <button onClick={runPath} disabled={!pathFrom.trim() || !pathTo.trim()}
              className="w-full px-3 py-1.5 rounded-[8px] bg-[var(--accent)] text-white text-[12px] font-medium disabled:opacity-40">{t("graph_path_find")}</button>
            {pathRes && (pathRes.found ? (
              <div className="mt-2.5 text-[12.5px] leading-relaxed border-t border-[var(--line)] pt-2.5 flex flex-wrap items-center gap-x-1 gap-y-1">
                <span className="font-semibold text-[var(--txt)]">{pathRes.path[0] ?? pathRes.from}</span>
                {pathRes.hops.map((h, i) => (
                  <span key={i} className="inline-flex items-center gap-1">
                    <span className="text-[var(--gold)] text-[11px]">→ {predLabel(h.predicate, t)} →</span>
                    <span className="font-semibold text-[var(--txt)]">{pathRes.path[i + 1]}</span>
                  </span>
                ))}
              </div>
            ) : (
              <div className="mt-2.5 text-[12px] text-[var(--dim)] border-t border-[var(--line)] pt-2.5">{t("graph_no_path")}</div>
            ))}
          </div>
        )}

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

        {!loaded ? (
          <div className="w-full h-full grid place-items-center text-[var(--dim)] card-surface">{t("loading")}</div>
        ) : shown.nodes.length === 0 ? (
          <div className="w-full h-full grid place-items-center text-[var(--dim)] card-surface">{t("graph_empty")}</div>
        ) : (
          <GraphCanvas ref={gref} data={shown} communities={communities} colorFor={colorFor} onPick={setPicked} nodeTint={tint}
            onHover={(id, x, y) => setHover(id ? { id, x, y } : null)} pathIds={pathIds}
            layout={layout} groupKey={colorBy} groupOf={groupOf} spotlight={picked}
            centerLabel={ns === "__all__" ? "✦" : ns} />
        )}

        {/* hover preview — the entity's top facts without a click (Obsidian-style) */}
        {hover && hoverInfo && (() => {
          const cw = wrapRef.current?.clientWidth ?? 800;
          const left = hover.x > cw - 290 ? Math.max(8, hover.x - 274) : hover.x + 16;
          return (
            <div className="absolute z-[5] pointer-events-none glass border border-[var(--line)] rounded-[11px] p-3 w-[260px] shadow-[var(--shadow)] fadein"
              style={{ left, top: Math.min(hover.y + 14, (wrapRef.current?.clientHeight ?? 600) - 140) }}>
              <div className="font-semibold text-[13px] text-[var(--txt)] truncate">{hoverInfo.name}</div>
              {hoverInfo.type && <div className="text-[10px] text-[var(--dim2)] uppercase tracking-wide mb-1">{hoverInfo.type}</div>}
              {hoverInfo.mems.length ? hoverInfo.mems.map((m: any) => (
                <div key={m.id} className="text-[12px] text-[var(--dim)] leading-snug mt-1 line-clamp-2">• {m.content}</div>
              )) : <div className="text-[11.5px] text-[var(--dim2)] mt-1">{t("nothing_here")}</div>}
            </div>
          );
        })()}

        {picked && (
          <NodeDetail ns={ns} name={picked} onClose={() => setPicked(null)}
            onOpenMemory={(m) => onOpenMemory?.(m)} onPickEntity={(n) => setPicked(n)}
            onFocus={(n) => { setFocusNode(n); setDepth(2); setPicked(null); }} />
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
                    <div className="flex justify-between text-[10px] text-[var(--dim2)]"><span>{t("cent_low")}</span><span>{t("cent_hub")}</span></div>
                  </div>
                ) : colorBy === "type" ? (
                  <div className="flex flex-col gap-1.5">
                    <div className="text-[var(--dim2)] text-[10px] mb-0.5">{t("graph_colored_by_type")}</div>
                    {typesPresent.map((ty) => (
                      <span key={ty} className="inline-flex items-center gap-2 text-[var(--dim)]">
                        <span className="w-2.5 h-2.5 rounded-full flex-none" style={{ background: valueColor(ty) }} />
                        <span className="truncate">{ty}</span>
                      </span>
                    ))}
                  </div>
                ) : colorBy === "channel" ? (
                  <div className="flex flex-col gap-1.5">
                    <div className="text-[var(--dim2)] text-[10px] mb-0.5">{t("graph_colored_by_channel")}</div>
                    {channelsPresent.map((ch) => (
                      <span key={ch} className="inline-flex items-center gap-2 text-[var(--dim)]">
                        <span className="w-2.5 h-2.5 rounded-full flex-none" style={{ background: valueColor(ch) }} />
                        <span className="truncate">{ch}</span>
                      </span>
                    ))}
                  </div>
                ) : colorBy === "area" ? (
                  <div className="flex flex-col gap-2">
                    <div className="text-[var(--dim2)] text-[10px] mb-0.5">{t("graph_colored_by_area")}</div>
                    {AREAS.filter((a) => dimsByArea[a.id]?.length).map((a) => (
                      <div key={a.id} className="flex flex-col gap-1">
                        <span className="text-[var(--dim2)] text-[10px] uppercase tracking-[.5px]" style={{ color: a.color }}>{a.label}</span>
                        {dimsByArea[a.id].map((dim) => (
                          <span key={dim} className="inline-flex items-center gap-2 text-[var(--dim)] pl-1">
                            <span className="w-2.5 h-2.5 rounded-full flex-none" style={{ background: valueColor(dim) }} />
                            <span className="truncate capitalize">{dimLabel(dim)}</span>
                          </span>
                        ))}
                      </div>
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
                    <span key={p} className="inline-flex items-center gap-2 text-[var(--dim)]"><span className="w-3 border-t-2 flex-none" style={{ borderColor: PCLASS_HEX[p] }} />{t(("pclass_" + p) as any)}</span>
                  ))}
                  {coMention && <span className="inline-flex items-center gap-2 text-[var(--dim)]"><span className="w-3 border-t border-dashed flex-none" style={{ borderColor: "#7888aa" }} />{t("glayer_comention")}</span>}
                  {suggest && <span className="inline-flex items-center gap-2 text-[var(--dim)]"><span className="w-3 border-t border-dashed flex-none" style={{ borderColor: "#f59e0b" }} />{t("legend_suggested")}</span>}
                  <span className="inline-flex items-center gap-2 text-[var(--dim)]"><span className="w-2.5 h-2.5 rounded-full border border-dashed flex-none" style={{ borderColor: "#f59e0b" }} />{t("legend_bridge")}</span>
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
