import { useEffect, useState } from "react";
import { GitMerge, Radius, Sparkles } from "lucide-react";
import { api, type Observation } from "../api";
import { useI18n } from "../i18n";
import { useNav } from "../navctx";

export default function Observations({ ns }: { ns: string }) {
  const { t } = useI18n();
  const [obs, setObs] = useState<Observation[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    api.observations(ns)
      .then((d) => { if (live) setObs(d.observations || []); })
      .catch(() => { if (live) setObs([]); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [ns]);

  const hubs = obs.filter((o) => o.kind === "hub");
  const cooc = obs.filter((o) => o.kind === "co_occurrence");

  return (
    <div className="fadein">
      <div className="flex items-baseline gap-3 mb-1">
        <h2 className="m-0 text-[18px] font-bold tracking-tight">{t("observations")}</h2>
        <span className="text-[var(--dim2)] text-[12.5px]">{t("observations_sub")}</span>
      </div>

      {loading ? (
        <div className="text-[var(--dim)] card-surface text-center py-10 mt-4">…</div>
      ) : obs.length === 0 ? (
        <div className="text-[var(--dim)] card-surface text-center py-10 mt-4">{t("observations_empty")}</div>
      ) : (
        <>
          {cooc.length > 0 && (
            <>
              <div className="flex items-center gap-2 mt-4 mb-2.5">
                <GitMerge size={13} className="text-[var(--accent2)]" />
                <span className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px]">{t("recurring_pairs")}</span>
              </div>
              {cooc.map((o, i) => <Card key={`c${i}`} o={o} icon="cooc" t={t} />)}
            </>
          )}
          {hubs.length > 0 && (
            <>
              <div className="flex items-center gap-2 mt-6 mb-2.5">
                <Radius size={13} className="text-[var(--gold)]" />
                <span className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px]">{t("central_entities")}</span>
              </div>
              {hubs.map((o, i) => <Card key={`h${i}`} o={o} icon="hub" t={t} />)}
            </>
          )}
        </>
      )}

      <div className="text-[11px] text-[var(--dim2)] mt-5 leading-snug flex items-start gap-1.5">
        <Sparkles size={12} className="mt-0.5 flex-none text-[var(--dim2)]" />
        {t("observations_foot")}
      </div>
    </div>
  );
}

function Card({ o, icon, t }: { o: Observation; icon: "hub" | "cooc"; t: (k: any) => string }) {
  const { onNs, onView } = useNav();
  const accent = icon === "hub" ? "var(--gold)" : "var(--accent2)";
  const go = () => { if (o.namespace) { onNs(o.namespace); onView("graph"); } };
  return (
    <div onClick={go} title={o.namespace ? t("open_in_graph") : undefined}
      className={`card-surface px-4 py-3 mb-2.5 ${o.namespace ? "cursor-pointer hover:bg-[var(--panel2)]" : ""}`}>
      <div className="flex items-center gap-2 flex-wrap mb-2">
        {o.entities.map((e, k) => (
          <span key={k} className="text-[12.5px] font-semibold px-2.5 py-1 rounded-lg border"
            style={{ borderColor: `${accent}55`, color: accent, background: `${accent}14` }}>{e}</span>
        ))}
        <span className="ml-auto text-[11px] tabular-nums text-[var(--dim2)] bg-[var(--panel2)] border border-[var(--line)] px-2 py-0.5 rounded-full">
          {o.count} {icon === "hub" ? t("relations_word") : t("shared_word")}
        </span>
        {o.namespace && <span className="text-[10.5px] text-[var(--dim2)]">{o.namespace}</span>}
      </div>
      <div className="text-[13px] text-[var(--dim)] leading-snug">{o.text}</div>
      {o.shared.length > 0 && (
        <div className="text-[11.5px] text-[var(--dim2)] mt-2 flex flex-wrap gap-1.5">
          {o.shared.map((s, k) => (
            <span key={k} className="bg-[var(--panel2)] border border-[var(--line)] px-2 py-px rounded-md">{s}</span>
          ))}
        </div>
      )}
    </div>
  );
}
