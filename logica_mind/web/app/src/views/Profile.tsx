import { useEffect, useRef, useState } from "react";
import { Send, Layers as LayersIcon, UserRound, FolderGit2, Building2, DollarSign, LayoutGrid, Network } from "lucide-react";
import { api, type DimensionsData, type DimensionEntry, type GraphData } from "../api";
import GraphCanvas, { type GraphHandle } from "../components/GraphCanvas";
import Markdown from "../components/Markdown";
import { useI18n } from "../i18n";
import { useNav, type MemFilter } from "../navctx";

const GROUP_COLOR: Record<string, string> = {
  personal: "#a78bfa", project: "#7c9cff", organization: "#22d3ee", business: "#4ade80",
};
// group / Maslow labels live in i18n — these map to the keys (rendered via t())
const GRP_KEY: Record<string, string> = {
  personal: "grp_person", project: "grp_projects", organization: "grp_organization", business: "grp_business",
};
const MASLOW_KEY: Record<string, string> = {
  "self-actualization": "maslow_self_actualization", esteem: "maslow_esteem", belonging: "maslow_belonging",
  safety: "maslow_safety", physiological: "maslow_physiological",
};

// build a navigable group → dimension → category graph from the dimension profile.
// `groupLabel` resolves a group id to its (translated) display label, which doubles
// as the node id, so the map speaks the active language.
function buildCatGraph(dims: DimensionEntry[], groupLabel: (g: string) => string): { data: GraphData; meta: Record<string, MemFilter | { group: string }> } {
  const nodes: GraphData["nodes"] = [];
  const links: GraphData["links"] = [];
  const meta: Record<string, any> = {};
  const groups = new Set<string>();
  for (const d of dims) {
    if (!d.count) continue;
    groups.add(d.group);
    const dimId = d.label;
    nodes.push({ id: dimId, namespaces: [d.group] });
    meta[dimId] = { dimension: d.id, label: d.label };
    links.push({ source: groupLabel(d.group), target: dimId, label: "" });
    for (const c of d.categories) {
      if (!meta[c.name]) { nodes.push({ id: c.name, namespaces: [d.group] }); meta[c.name] = { category: c.name, label: c.name }; }
      links.push({ source: dimId, target: c.name, label: "" });
    }
  }
  for (const g of groups) { const gl = groupLabel(g); nodes.unshift({ id: gl, namespaces: [g], shared: true }); meta[gl] = { group: g }; }
  return { data: { nodes, links }, meta };
}

// the unified profile: the dialectic user model + the dimension/category map,
// organized by the four life/work groups. Labels resolve through i18n at render.
const TABS = [
  { id: "personal", labelKey: "grp_person", color: "#a78bfa", Icon: UserRound },
  { id: "project", labelKey: "grp_projects", color: "#7c9cff", Icon: FolderGit2 },
  { id: "organization", labelKey: "grp_organization", color: "#22d3ee", Icon: Building2 },
  { id: "business", labelKey: "grp_business", color: "#4ade80", Icon: DollarSign },
];

export default function Profile({ ns }: { ns: string }) {
  const { t } = useI18n();
  const { onMemories } = useNav();
  const [data, setData] = useState<DimensionsData | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [tab, setTab] = useState("personal");
  const [mode, setMode] = useState<"cards" | "map">("cards");
  const graphRef = useRef<GraphHandle>(null);
  // user model (Person tab)
  const [profile, setProfile] = useState("");
  const [q, setQ] = useState("");
  const [answer, setAnswer] = useState("");
  const [asking, setAsking] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setLoaded(false); setAnswer("");
    api.dimensions(ns).then((d) => { setData(d); setLoaded(true); }).catch(() => setLoaded(true));
    api.user(ns).then((d) => setProfile(d.profile || "")).catch(() => setProfile(""));
  }, [ns]);

  async function ask() {
    if (!q.trim() || asking) return;
    setAsking(true); setAnswer("");
    try { const res = await api.askAboutUser(ns, q.trim()); setAnswer(res.answer || res.insight || ""); }
    catch { setAnswer("—"); }
    setAsking(false);
  }

  const openFilter = (f: MemFilter) => onMemories(ns, f);
  const dims = (data?.dimensions || []);
  const groupCount = (g: string) => dims.filter((d) => d.group === g).reduce((a, d) => a + d.count, 0);
  const active = TABS.find((x) => x.id === tab)!;
  const tabDims = dims.filter((d) => d.group === tab && d.count > 0);

  return (
    <div className="fadein">
      <div className="flex items-baseline gap-3 mb-1">
        <h2 className="m-0 text-[18px] font-bold tracking-tight">{t("profile")} · {ns === "__all__" ? t("all_word") : ns}</h2>
        <span className="text-[var(--dim2)] text-[12.5px] max-[680px]:hidden">{t("profile_sub")}</span>
        <div className="ml-auto flex gap-1">
          <button onClick={() => setMode("cards")} title={t("profile_cards")}
            className={`p-1.5 rounded-lg border ${mode === "cards" ? "bg-[var(--panel2)] text-[var(--txt)] border-[var(--line)]" : "border-[var(--line)] text-[var(--dim)]"}`}><LayoutGrid size={15} /></button>
          <button onClick={() => setMode("map")} title={t("profile_map")}
            className={`p-1.5 rounded-lg border ${mode === "map" ? "bg-[var(--panel2)] text-[var(--txt)] border-[var(--line)]" : "border-[var(--line)] text-[var(--dim)]"}`}><Network size={15} /></button>
        </div>
      </div>

      {/* map mode: the group → dimension → category graph */}
      {mode === "map" && (() => {
        const { data: gd, meta } = buildCatGraph(dims, (g) => t(GRP_KEY[g] as any) || g);
        return gd.nodes.length ? (
          <div className="h-[600px] mt-4">
            <GraphCanvas ref={graphRef} data={gd} communities={false}
              colorFor={(g) => GROUP_COLOR[g] || "#7c9cff"}
              onPick={(id) => { const m = meta[id]; if (!m) return; if ("group" in m) setTab((m as any).group); else openFilter(m as MemFilter); }} />
          </div>
        ) : (
          <div className="card-surface text-center py-12 mt-4 text-[var(--dim)]">{t("profile_empty")}</div>
        );
      })()}

      {/* group tabs (cards mode) */}
      {mode === "cards" && <>
      <div className="flex gap-1.5 my-4 flex-wrap">
        {TABS.map(({ id, labelKey, color, Icon }) => {
          const on = tab === id;
          const c = groupCount(id);
          return (
            <button key={id} onClick={() => setTab(id)}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-[10px] border text-[13px] font-medium ${
                on ? "text-[var(--txt)]" : "border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)]"}`}
              style={on ? { borderColor: color, background: `${color}14` } : {}}>
              <Icon size={15} style={{ color: on ? color : undefined }} /> {t(labelKey as any)}
              <span className="tabular-nums text-[11.5px]" style={{ color }}>{c}</span>
            </button>
          );
        })}
      </div>

      {/* Person tab: the dialectic user model + ask box */}
      {tab === "personal" && (
        <div className="card-surface p-4 mb-4">
          <div className="text-[var(--dim2)] text-[11px] uppercase tracking-[.7px] mb-2.5">{t("user_model")}</div>
          <div className="flex gap-2 mb-3">
            <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask()}
              placeholder={t("ask_about_user_ph")}
              className="flex-1 bg-[var(--panel2)] border border-[var(--line)] rounded-[9px] px-3 py-2 text-[13px] text-[var(--txt)] outline-none focus:border-[var(--accent)]/60" />
            <button onClick={ask} disabled={asking || !q.trim()}
              className="px-3.5 py-2 rounded-[9px] bg-[var(--accent)] text-white text-[12.5px] font-medium disabled:opacity-40 flex items-center gap-1.5">
              <Send size={13} /> {asking ? t("asking") : t("ask_btn")}
            </button>
          </div>
          {answer && <Markdown text={answer} className="text-[13px] text-[var(--txt)] leading-relaxed border-t border-[var(--line)] pt-3 mb-3" />}
          {profile
            ? <Markdown text={profile} className="text-[13px] text-[var(--dim)] leading-[1.6]" />
            : <div className="text-[var(--dim2)] text-[12.5px]">{t("no_user_model")}</div>}
        </div>
      )}

      {/* dimension cards for the active group */}
      {!loaded ? (
        <div className="text-[var(--dim)] py-10 text-center">{t("loading")}</div>
      ) : tabDims.length === 0 ? (
        <div className="card-surface text-center py-10 text-[var(--dim)]">
          <LayersIcon size={24} className="mx-auto mb-2.5 text-[var(--dim2)]" />
          <div className="text-[13.5px] text-[var(--txt)] font-medium mb-1">{t("profile_empty")}</div>
          <div className="text-[12px]">{t("profile_empty_hint")}</div>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2.5 max-[760px]:grid-cols-1">
          {tabDims.map((d) => <DimCard key={d.id} d={d} color={active.color} onOpen={openFilter} t={t} />)}
        </div>
      )}
      </>}
    </div>
  );
}

function DimCard({ d, color, onOpen, t }: { d: DimensionEntry; color: string; onOpen: (f: MemFilter) => void; t: (k: any) => string }) {
  return (
    <div className="card-surface px-4 py-3">
      <button onClick={() => onOpen({ dimension: d.id, label: d.label })} title={t("open_in_memories")}
        className="w-full flex items-center gap-2 mb-2 text-left group">
        <span className="text-[13px] font-semibold group-hover:text-[var(--accent)]">{d.label}</span>
        {d.maslow && <span className="text-[10px] text-[var(--dim2)] bg-[var(--panel2)] border border-[var(--line)] px-1.5 py-px rounded-full">{t(MASLOW_KEY[d.maslow] as any) || d.maslow}</span>}
        <span className="ml-auto text-[12px] tabular-nums font-bold" style={{ color }}>{d.count}</span>
      </button>
      <div className="flex flex-wrap gap-1.5">
        {d.categories.map((c) => (
          <button key={c.name} onClick={() => onOpen({ category: c.name, label: c.name })} title={t("open_in_memories")}
            className="flex items-center gap-1.5 text-[11.5px] px-2 py-1 rounded-lg border border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)] hover:border-[var(--accent)]/60">
            {c.name}<span className="tabular-nums text-[var(--dim2)]">{c.count}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
