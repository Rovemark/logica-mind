import { useEffect, useMemo, useRef, useState } from "react";
import { api, ALL, valueColor, type NsItem, type Memory } from "./api";
import { VIEWS, type ViewKey } from "./nav";
import { LangCtx, makeT, getLang, saveLang, loadLang, type Lang } from "./i18n";
import { MemoryOpenCtx } from "./memctx";
import { NavCtx, type MemFilter } from "./navctx";
import MemoryDetail from "./components/MemoryDetail";
import Sidebar from "./components/Sidebar";
import Topbar from "./components/Topbar";
import DemoBanner from "./components/DemoBanner";
import TabBar from "./components/TabBar";
import CommandPalette from "./components/CommandPalette";
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
import Profile from "./views/Profile";
import Peers from "./views/Peers";
import Changes from "./views/Changes";
import Insights from "./views/Insights";
import Workspace from "./views/Workspace";
import Dreams from "./views/Dreams";

const VIEW_SET = new Set([...VIEWS.map((v) => v.key as string), "settings"]);
// clean, real URLs (history routing) — '/graph/org:acme', no '#'. The Python
// server already serves the app shell for any unknown non-API path, so deep
// links and refresh work. (Was hash routing; the '#' is gone.)
function parseHash(): { view: ViewKey; ns: string } {
  const p = decodeURIComponent(location.pathname.replace(/^\/+/, "").replace(/\/+$/, ""));
  const [v, ...rest] = p.split("/");
  return { view: (VIEW_SET.has(v) ? v : "overview") as ViewKey, ns: rest.length ? rest.join("/") : ALL };
}
function writeHash(view: ViewKey, ns: string) {
  // keep ':' readable in the path (it's safe there): '/graph/org:acme'
  const enc = ns && ns !== ALL ? "/" + encodeURIComponent(ns).replace(/%3A/gi, ":") : "";
  const p = view === "overview" && (!ns || ns === ALL) ? "/" : `/${view}${enc}`;
  if (location.pathname !== p) history.pushState(null, "", p);
}

export default function App() {
  const init = parseHash();
  const [namespaces, setNamespaces] = useState<NsItem[]>([]);
  const [ns, setNs] = useState<string>(init.ns);
  const [view, setView] = useState<ViewKey>(init.view);
  const [palette, setPalette] = useState(false);
  const [memFilter, setMemFilter] = useState<MemFilter | null>(null);
  const [graphFocus, setGraphFocus] = useState<{ name: string; n: number } | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [rev, setRev] = useState(0);
  const [lang, setLangState] = useState<Lang>(getLang());
  const [openMem, setOpenMem] = useState<Memory | null>(null);
  // PERGUNTA: "meu appliance tem ZERO memórias?"
  // A contagem do topo nascia em 0 e só virava 83.749 quando /namespaces voltava.
  // Nesse intervalo o painel afirmava, com todas as letras, que a memória estava
  // vazia — a pior mentira que este produto pode contar. Este sinal separa
  // "ainda não sei" de "é zero mesmo".
  const [nsPronto, setNsPronto] = useState(false);
  const colorsRef = useRef<Record<string, string>>({});
  const [langRev, setLangRev] = useState(0);
  const t = useMemo(() => makeT(lang), [lang, langRev]);
  const setLang = (l: Lang) => { saveLang(l); setLangState(l); };
  // load the active language's chunk on demand, then re-render with it; also set
  // RTL for Arabic and <html lang> for a11y
  useEffect(() => {
    let live = true;
    loadLang(lang).then(() => { if (live) setLangRev((r) => r + 1); });
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
    document.documentElement.lang = lang;
    return () => { live = false; };
  }, [lang]);

  const loadNs = () => api.namespaces().then((d) => {
    d.namespaces.forEach((n) => { if (!(n.namespace in colorsRef.current)) colorsRef.current[n.namespace] = valueColor(n.namespace); });
    setNamespaces(d.namespaces);
  }).catch(() => {}).finally(() => setNsPronto(true));   // erro também encerra a espera: melhor "0" que "—" pra sempre
  const bump = () => { setRev((r) => r + 1); loadNs(); };   // after a write: refetch view + counts

  // open any memory as an Obsidian-style note pane (Properties + content + provenance)
  const openMemory = (m: Memory) => setOpenMem(m);

  useEffect(() => {
    loadNs();
    const t = setInterval(loadNs, 8000);
    // URL routing: each view (and namespace) has its own real path, so back/
    // forward and deep-links work — /graph, /sessions/research …
    const onHash = () => { const p = parseHash(); setView(p.view); setNs(p.ns); };
    window.addEventListener("popstate", onHash);
    // ⌘K / Ctrl-K opens the global Spotlight from anywhere
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) { e.preventDefault(); setPalette((p) => !p); }
    };
    window.addEventListener("keydown", onKey);
    writeHash(view, ns);
    return () => { clearInterval(t); window.removeEventListener("popstate", onHash); window.removeEventListener("keydown", onKey); };
    // eslint-disable-next-line
  }, []);

  const total = useMemo(() => {
    if (ns === ALL) return namespaces.reduce((a, n) => a + n.total, 0);
    return namespaces.find((n) => n.namespace === ns)?.total ?? 0;
  }, [ns, namespaces]);

  const colorFor = (name: string) => colorsRef.current[name] || "#7c9cff";
  const closeDrawer = () => setDrawer(false);
  const onView = (v: ViewKey) => { setMemFilter(null); setView(v); closeDrawer(); writeHash(v, ns); };
  const onNs = (n: string) => { setNs(n); closeDrawer(); writeHash(view, n); };

  const View = { overview: Overview, analytics: Analytics, context: ContextBlock, graph: GraphView, memories: Memories, calendar: Calendar, sessions: Sessions, user: UserModel, profile: Profile, peers: Peers, observations: Observations, changes: Changes, insights: Insights, workspace: Workspace, dreams: Dreams, settings: Settings }[view];

  return (
    <LangCtx.Provider value={{ lang, setLang, t }}>
    <NavCtx.Provider value={{ onView, onNs,
      onMemories: (n, f) => { setMemFilter(f || null); setNs(n); setView("memories"); closeDrawer(); writeHash("memories", n); },
      onEntity: (n, name) => { setNs(n); setView("graph"); setGraphFocus({ name, n: Date.now() }); setOpenMem(null); closeDrawer(); writeHash("graph", n); } }}>
    <MemoryOpenCtx.Provider value={openMemory}>
    <div className="grid h-screen grid-cols-[256px_1fr] max-[820px]:grid-cols-[1fr]">
      <Sidebar view={view} ns={ns} namespaces={namespaces} colors={colorsRef.current}
        open={drawer} onView={onView} onNs={onNs} onClose={closeDrawer} onSettings={() => onView("settings")}
        pronto={nsPronto} />

      <main className="flex flex-col min-w-0 min-h-0">
        <Topbar view={view} ns={ns} total={total} pronto={nsPronto} onOpen={() => setPalette(true)} action={<Composer ns={ns} onDone={bump} />} />
        <DemoBanner onChange={bump} />
        <div className="flex-1 min-h-0 overflow-auto flex flex-col px-6 pt-[22px] pb-[30px] max-[820px]:px-3.5 max-[820px]:pb-[92px]">
          <View key={`${view}-${ns}-${rev}`} ns={ns} colorFor={colorFor} onOpenMemory={openMemory} onChanged={bump} filter={memFilter} focusEntity={graphFocus} />
          {/* Rodapé DE PÁGINA — o wrapper com mt-auto desce o rodapé até o fundo
              em view curta (em view longa ele segue o conteúdo, com respiro
              pt-12); o -mx-6 fura o padding do container pra faixa atravessar a
              largura INTEIRA. */}
          <div className="mt-auto pt-12">
          <footer className="-mx-6 flex flex-wrap items-center gap-x-6 gap-y-3 border-t border-[var(--line)] px-6 pt-5 max-[820px]:-mx-3.5 max-[820px]:px-3.5">
            <div className="flex items-center gap-2.5">
              <span className="w-7 h-7">
                <img src="/logicaos-halo-dark-64.png" alt="" className="lr-logo-dark w-full h-full" />
                <img src="/logicaos-halo-light-64.png" alt="" className="lr-logo-light w-full h-full" />
              </span>
              <span>
                <b className="block text-[12.5px] leading-tight tracking-tight">LogicaOS</b>
                <span className="mono text-[9px] uppercase tracking-[0.14em] text-[var(--dim2)]">The Operating Layer for Sovereign AI</span>
              </span>
            </div>
            <div className="ml-auto flex items-center gap-1.5 opacity-60 transition-opacity duration-300 hover:opacity-100"
              title="Logica Mind — produto Rovemark · Ambrosio Company">
              <span className="text-[9.5px] uppercase tracking-[0.14em] text-[var(--dim2)]">por</span>
              <img src="/rovemark-logo-white.svg" alt="Rovemark" className="lr-logo-dark h-[19px] w-auto" />
              <img src="/rovemark-logo-black.svg" alt="Rovemark" className="lr-logo-light h-[19px] w-auto" />
            </div>
          </footer>
          </div>
        </div>
      </main>

      <TabBar view={view} onView={onView} onMenu={() => setDrawer(true)} />
      {drawer && <div className="fixed inset-0 z-40 bg-black/55 backdrop-blur-[2px] hidden max-[820px]:block" onClick={closeDrawer} />}
      {palette && <CommandPalette namespaces={namespaces} onClose={() => setPalette(false)}
        onView={onView} onNs={onNs} onOpenMemory={openMemory} />}
      {openMem && <MemoryDetail memory={openMem} onClose={() => setOpenMem(null)} />}
    </div>
    </MemoryOpenCtx.Provider>
    </NavCtx.Provider>
    </LangCtx.Provider>
  );
}
