import { useEffect, useMemo, useRef, useState } from "react";
import { api, ALL, PALETTE, type NsItem, type RecallHit, type Memory } from "./api";
import { VIEWS, type ViewKey } from "./nav";
import { LangCtx, makeT, getLang, saveLang, type Lang } from "./i18n";
import { MemoryOpenCtx } from "./memctx";
import MemoryDetail from "./components/MemoryDetail";
import Sidebar from "./components/Sidebar";
import Topbar from "./components/Topbar";
import DemoBanner from "./components/DemoBanner";
import TabBar from "./components/TabBar";
import MemoryCard from "./components/MemoryCard";
import Composer from "./components/Composer";
import Settings from "./components/Settings";
import Overview from "./views/Overview";
import Analytics from "./views/Analytics";
import ContextBlock from "./views/ContextBlock";
import Observations from "./views/Observations";
import GraphView from "./views/GraphView";
import Memories from "./views/Memories";
import Calendar from "./views/Calendar";
import Sessions from "./views/Sessions";
import UserModel from "./views/UserModel";
import Peers from "./views/Peers";
import Changes from "./views/Changes";
import Insights from "./views/Insights";
import Workspace from "./views/Workspace";
import Dreams from "./views/Dreams";

const VIEW_SET = new Set(VIEWS.map((v) => v.key as string));
function parseHash(): { view: ViewKey; ns: string } {
  const h = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
  const [v, ...rest] = h.split("/");
  return { view: (VIEW_SET.has(v) ? v : "overview") as ViewKey, ns: rest.length ? rest.join("/") : ALL };
}
function writeHash(view: ViewKey, ns: string) {
  const h = `#/${view}${ns && ns !== ALL ? "/" + encodeURIComponent(ns) : ""}`;
  if (location.hash !== h) location.hash = h;
}

export default function App() {
  const init = parseHash();
  const [namespaces, setNamespaces] = useState<NsItem[]>([]);
  const [ns, setNs] = useState<string>(init.ns);
  const [view, setView] = useState<ViewKey>(init.view);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<RecallHit[]>([]);
  const [drawer, setDrawer] = useState(false);
  const [rev, setRev] = useState(0);
  const [lang, setLangState] = useState<Lang>(getLang());
  const [showSettings, setShowSettings] = useState(false);
  const [openMem, setOpenMem] = useState<Memory | null>(null);
  const colorsRef = useRef<Record<string, string>>({});
  const t = useMemo(() => makeT(lang), [lang]);
  const setLang = (l: Lang) => { saveLang(l); setLangState(l); };

  const loadNs = () => api.namespaces().then((d) => {
    d.namespaces.forEach((n, i) => { if (!(n.namespace in colorsRef.current)) colorsRef.current[n.namespace] = PALETTE[i % PALETTE.length]; });
    setNamespaces(d.namespaces);
  }).catch(() => {});
  const bump = () => { setRev((r) => r + 1); loadNs(); };   // after a write: refetch view + counts

  // open any memory as an Obsidian-style note pane (Properties + content + provenance)
  const openMemory = (m: Memory) => setOpenMem(m);

  useEffect(() => {
    loadNs();
    const t = setInterval(loadNs, 8000);
    // URL routing: each view (and namespace) has its own hash, so back/forward and
    // deep-links work — #/graph, #/sessions/research …
    const onHash = () => { const p = parseHash(); setView(p.view); setNs(p.ns); };
    window.addEventListener("hashchange", onHash);
    writeHash(view, ns);
    return () => { clearInterval(t); window.removeEventListener("hashchange", onHash); };
    // eslint-disable-next-line
  }, []);

  // debounced recall
  useEffect(() => {
    if (!q.trim()) { setHits([]); return; }
    const t = setTimeout(() => { api.recall(ns, q, 15).then((d) => setHits(d.results)).catch(() => setHits([])); }, 250);
    return () => clearTimeout(t);
  }, [q, ns]);

  const total = useMemo(() => {
    if (ns === ALL) return namespaces.reduce((a, n) => a + n.total, 0);
    return namespaces.find((n) => n.namespace === ns)?.total ?? 0;
  }, [ns, namespaces]);

  const colorFor = (name: string) => colorsRef.current[name] || "#7c9cff";
  const closeDrawer = () => setDrawer(false);
  const onView = (v: ViewKey) => { setView(v); setQ(""); closeDrawer(); writeHash(v, ns); };
  const onNs = (n: string) => { setNs(n); closeDrawer(); writeHash(view, n); };

  const View = { overview: Overview, analytics: Analytics, context: ContextBlock, graph: GraphView, memories: Memories, calendar: Calendar, sessions: Sessions, user: UserModel, peers: Peers, observations: Observations, changes: Changes, insights: Insights, workspace: Workspace, dreams: Dreams }[view];

  return (
    <LangCtx.Provider value={{ lang, setLang, t }}>
    <MemoryOpenCtx.Provider value={openMemory}>
    <div className="grid h-screen grid-cols-[256px_1fr] max-[820px]:grid-cols-[1fr]">
      <Sidebar view={view} ns={ns} namespaces={namespaces} colors={colorsRef.current}
        open={drawer} onView={onView} onNs={onNs} onClose={closeDrawer} onSettings={() => setShowSettings(true)} />

      <main className="flex flex-col min-w-0 min-h-0">
        <Topbar q={q} ns={ns} total={total} onSearch={setQ} action={<Composer ns={ns} onDone={bump} />} />
        <DemoBanner onChange={bump} />
        <div className="flex-1 min-h-0 overflow-auto px-6 pt-[22px] pb-[30px] max-[820px]:px-3.5 max-[820px]:pb-[92px]">
          {q.trim() ? (
            <div className="fadein">
              <h2 className="m-0 mb-4 text-[18px] font-bold tracking-tight">{t("recall")} · “{q}”</h2>
              {hits.length ? hits.map((h, i) => <MemoryCard key={i} m={h.memory} score={h.score} components={h.components} />)
                : <div className="text-[var(--dim)] text-center py-12">{t("no_match")}</div>}
            </div>
          ) : (
            <View key={`${view}-${ns}-${rev}`} ns={ns} colorFor={colorFor} onOpenMemory={openMemory} onChanged={bump} />
          )}
        </div>
      </main>

      <TabBar view={view} onView={onView} onMenu={() => setDrawer(true)} />
      {drawer && <div className="fixed inset-0 z-40 bg-black/55 backdrop-blur-[2px] hidden max-[820px]:block" onClick={closeDrawer} />}
      {showSettings && <Settings ns={ns} onClose={() => setShowSettings(false)} />}
      {openMem && <MemoryDetail memory={openMem} onClose={() => setOpenMem(null)} />}
    </div>
    </MemoryOpenCtx.Provider>
    </LangCtx.Provider>
  );
}
