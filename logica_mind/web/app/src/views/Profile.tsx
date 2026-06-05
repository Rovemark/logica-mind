import { useEffect, useState } from "react";
import { Layers as LayersIcon } from "lucide-react";
import { api, type DimensionsData, type DimensionEntry } from "../api";
import { useI18n } from "../i18n";
import { useNav } from "../navctx";

// group + maslow colors
const GROUP_COLOR: Record<string, string> = {
  personal: "#a78bfa", project: "#7c9cff", organization: "#22d3ee", business: "#4ade80",
};
const GROUP_ORDER = ["personal", "project", "organization", "business"];
const GROUP_LABEL: Record<string, string> = {
  personal: "Personal", project: "Projects", organization: "Organization", business: "Business & Finance",
};
const MASLOW_LABEL: Record<string, string> = {
  "self-actualization": "Self-actualization", esteem: "Esteem", belonging: "Love & Belonging",
  safety: "Safety", physiological: "Physiological",
};

export default function Profile({ ns }: { ns: string }) {
  const { t } = useI18n();
  const { onNs, onView } = useNav();
  const [data, setData] = useState<DimensionsData | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setLoaded(false);
    api.dimensions(ns).then((d) => { setData(d); setLoaded(true); }).catch(() => setLoaded(true));
  }, [ns]);

  // jump to this namespace's memories (the category chip is also a quick label)
  const openCat = (_cat: string) => { onNs(ns); onView("memories"); };

  if (!loaded) return <div className="fadein text-[var(--dim)] py-16 text-center">{t("loading")}</div>;
  const dims = (data?.dimensions || []).filter((d) => d.count > 0);
  const total = dims.reduce((a, d) => a + d.count, 0);

  return (
    <div className="fadein">
      <div className="flex items-baseline gap-3 mb-1">
        <h2 className="m-0 text-[18px] font-bold tracking-tight">{t("profile")}</h2>
        <span className="text-[var(--dim2)] text-[12.5px]">{t("profile_sub")}</span>
      </div>

      {total === 0 ? (
        <div className="card-surface text-center py-12 mt-4 text-[var(--dim)]">
          <LayersIcon size={26} className="mx-auto mb-3 text-[var(--dim2)]" />
          <div className="text-[14px] text-[var(--txt)] font-medium mb-1">{t("profile_empty")}</div>
          <div className="text-[12.5px]">{t("profile_empty_hint")}</div>
        </div>
      ) : (
        <>
          {/* group summary strip */}
          <div className="grid gap-2.5 my-4" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))" }}>
            {GROUP_ORDER.map((g) => {
              const c = dims.filter((d) => d.group === g).reduce((a, d) => a + d.count, 0);
              const col = GROUP_COLOR[g];
              return (
                <div key={g} className="card-surface px-4 py-3">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-2 h-2 rounded-full" style={{ background: col }} />
                    <span className="text-[11px] uppercase tracking-[.6px] text-[var(--dim2)]">{GROUP_LABEL[g]}</span>
                  </div>
                  <div className="text-[20px] font-bold tabular-nums" style={{ color: col }}>{c}</div>
                </div>
              );
            })}
          </div>

          {GROUP_ORDER.map((g) => {
            const gdims = dims.filter((d) => d.group === g);
            if (!gdims.length) return null;
            return (
              <div key={g} className="mb-5">
                <div className="flex items-center gap-2 mb-2.5">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ background: GROUP_COLOR[g] }} />
                  <span className="text-[13px] font-bold">{GROUP_LABEL[g]}</span>
                  {g === "personal" && <span className="text-[11px] text-[var(--dim2)]">· {t("profile_maslow")}</span>}
                </div>
                <div className="grid grid-cols-2 gap-2.5 max-[760px]:grid-cols-1">
                  {gdims.map((d) => <DimCard key={d.id} d={d} color={GROUP_COLOR[g]} onCat={openCat} t={t} />)}
                </div>
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}

function DimCard({ d, color, onCat, t }: { d: DimensionEntry; color: string; onCat: (c: string) => void; t: (k: any) => string }) {
  return (
    <div className="card-surface px-4 py-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[13px] font-semibold">{d.label}</span>
        {d.maslow && <span className="text-[10px] text-[var(--dim2)] bg-[var(--panel2)] border border-[var(--line)] px-1.5 py-px rounded-full">{MASLOW_LABEL[d.maslow] || d.maslow}</span>}
        <span className="ml-auto text-[12px] tabular-nums font-bold" style={{ color }}>{d.count}</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {d.categories.map((c) => (
          <button key={c.name} onClick={() => onCat(c.name)}
            title={t("open_in_memories")}
            className="flex items-center gap-1.5 text-[11.5px] px-2 py-1 rounded-lg border border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)] hover:border-[var(--accent)]/60">
            {c.name}
            <span className="tabular-nums text-[var(--dim2)]">{c.count}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
