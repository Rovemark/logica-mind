import { useEffect, useState } from "react";
import { api, LAYERS, type Memory, type Stats } from "../api";
import MemoryCard from "../components/MemoryCard";
import InsightList from "../components/InsightList";
import { useI18n } from "../i18n";

export default function Overview({ ns }: { ns: string }) {
  const { t } = useI18n();
  const [stats, setStats] = useState<Stats | null>(null);
  const [insight, setInsight] = useState("");
  const [recent, setRecent] = useState<Memory[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    setLoaded(false);
    api.stats(ns).then((d) => setStats(d.stats)).catch(() => setStats(null));
    api.reflect(ns).then((d) => setInsight(d.insight || "")).catch(() => setInsight(""));
    api.memories(ns).then((d) => setRecent(d.memories.slice(0, 8))).catch(() => setRecent([])).finally(() => setLoaded(true));
  }, [ns]);

  return (
    <div className="fadein">
      <h2 className="m-0 mb-4 text-[18px] font-bold tracking-tight">{t("overview")}</h2>
      <div className="grid gap-3 mb-5" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(120px,1fr))" }}>
        <Stat k={t("total")} v={stats?.total ?? 0} />
        {LAYERS.map((l) => <Stat key={l} k={t(`layer_${l}` as any)} v={(stats as any)?.[l] ?? 0} cls={`lyr-${l}`} />)}
      </div>
      {insight && (
        <>
          <div className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px] mb-2.5">{t("insight")}</div>
          <div className="mb-[18px]"><InsightList text={insight} /></div>
        </>
      )}
      <div className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px] mb-2.5">{t("recent_activity")}</div>
      {!loaded ? <div className="text-[var(--dim)] text-center py-10">{t("loading")}</div>
        : recent.length ? recent.map((m) => <MemoryCard key={m.id} m={m} />)
        : <div className="text-[var(--dim)] text-center py-10">{t("no_memories_yet")}</div>}
    </div>
  );
}

function Stat({ k, v, cls }: { k: string; v: number; cls?: string }) {
  return (
    <div className="card-surface px-[17px] py-[15px]">
      <div className="text-[var(--dim)] text-[11px] uppercase tracking-[.6px]">{k}</div>
      <div className={`text-[26px] font-bold mt-0.5 tabular-nums ${cls || ""}`}>{v}</div>
    </div>
  );
}
