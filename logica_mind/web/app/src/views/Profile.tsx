import { useEffect, useRef, useState } from "react";
import { Send, Layers as LayersIcon, UserRound, FolderGit2, Building2, DollarSign } from "lucide-react";
import { api, type DimensionsData, type DimensionEntry } from "../api";
import { useI18n } from "../i18n";
import { useNav } from "../navctx";

// the unified profile: the dialectic user model + the dimension/category map,
// organized by the four life/work groups.
const TABS = [
  { id: "personal", label: "Person", color: "#a78bfa", Icon: UserRound },
  { id: "project", label: "Projects", color: "#7c9cff", Icon: FolderGit2 },
  { id: "organization", label: "Organization", color: "#22d3ee", Icon: Building2 },
  { id: "business", label: "Business", color: "#4ade80", Icon: DollarSign },
];
const MASLOW_LABEL: Record<string, string> = {
  "self-actualization": "Self-actualization", esteem: "Esteem", belonging: "Love & Belonging",
  safety: "Safety", physiological: "Physiological",
};

export default function Profile({ ns }: { ns: string }) {
  const { t } = useI18n();
  const { onNs, onView } = useNav();
  const [data, setData] = useState<DimensionsData | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [tab, setTab] = useState("personal");
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

  const openCat = () => { onNs(ns); onView("memories"); };
  const dims = (data?.dimensions || []);
  const groupCount = (g: string) => dims.filter((d) => d.group === g).reduce((a, d) => a + d.count, 0);
  const active = TABS.find((x) => x.id === tab)!;
  const tabDims = dims.filter((d) => d.group === tab && d.count > 0);

  return (
    <div className="fadein">
      <div className="flex items-baseline gap-3 mb-1">
        <h2 className="m-0 text-[18px] font-bold tracking-tight">{t("profile")} · {ns === "__all__" ? t("all_word") : ns}</h2>
        <span className="text-[var(--dim2)] text-[12.5px] max-[680px]:hidden">{t("profile_sub")}</span>
      </div>

      {/* group tabs */}
      <div className="flex gap-1.5 my-4 flex-wrap">
        {TABS.map(({ id, label, color, Icon }) => {
          const on = tab === id;
          const c = groupCount(id);
          return (
            <button key={id} onClick={() => setTab(id)}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-[10px] border text-[13px] font-medium ${
                on ? "text-[var(--txt)]" : "border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)]"}`}
              style={on ? { borderColor: color, background: `${color}14` } : {}}>
              <Icon size={15} style={{ color: on ? color : undefined }} /> {label}
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
          {answer && <div className="text-[13px] text-[var(--txt)] leading-relaxed border-t border-[var(--line)] pt-3 mb-3">{answer}</div>}
          {profile
            ? <pre className="whitespace-pre-wrap m-0 text-[13px] text-[var(--dim)] leading-[1.6]">{profile}</pre>
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
          {tabDims.map((d) => <DimCard key={d.id} d={d} color={active.color} onCat={openCat} t={t} />)}
        </div>
      )}
    </div>
  );
}

function DimCard({ d, color, onCat, t }: { d: DimensionEntry; color: string; onCat: () => void; t: (k: any) => string }) {
  return (
    <div className="card-surface px-4 py-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[13px] font-semibold">{d.label}</span>
        {d.maslow && <span className="text-[10px] text-[var(--dim2)] bg-[var(--panel2)] border border-[var(--line)] px-1.5 py-px rounded-full">{MASLOW_LABEL[d.maslow] || d.maslow}</span>}
        <span className="ml-auto text-[12px] tabular-nums font-bold" style={{ color }}>{d.count}</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {d.categories.map((c) => (
          <button key={c.name} onClick={onCat} title={t("open_in_memories")}
            className="flex items-center gap-1.5 text-[11.5px] px-2 py-1 rounded-lg border border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)] hover:border-[var(--accent)]/60">
            {c.name}<span className="tabular-nums text-[var(--dim2)]">{c.count}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
