import { useEffect, useMemo, useState } from "react";
import { ArrowRight } from "lucide-react";
import { api, tShort, type Contradiction, type DiffItem } from "../api";
import { LayerPill } from "../components/MemoryCard";
import { useI18n } from "../i18n";

const RANGES: [string, number][] = [["7d", 7], ["30d", 30], ["90d", 90]];

export default function Changes({ ns }: { ns: string }) {
  const { t } = useI18n();
  const [contras, setContras] = useState<Contradiction[]>([]);
  const [diff, setDiff] = useState<DiffItem[]>([]);
  const [days, setDays] = useState(30);

  const since = useMemo(() => {
    const d = new Date(); d.setDate(d.getDate() - days);
    return d.toISOString().replace(/\.\d+Z$/, "Z");
  }, [days]);

  useEffect(() => {
    api.contradictions(ns).then((d) => setContras(d.contradictions || [])).catch(() => setContras([]));
  }, [ns]);
  useEffect(() => {
    api.diff(ns, since).then((d) => setDiff(d.diff || [])).catch(() => setDiff([]));
  }, [ns, since]);

  return (
    <div className="fadein">
      <h2 className="m-0 mb-4 text-[18px] font-bold tracking-tight">{t("changes")}</h2>

      <div className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px] mb-2.5">{t("contradictions")}</div>
      {contras.length ? contras.map((c, i) => (
        <div key={i} className="card-surface px-4 py-3 mb-2.5">
          <div className="text-[13px] text-[var(--dim)] mb-2">
            <span className="text-[var(--txt)] font-semibold">{c.subject}</span>{" "}
            <span className="text-[var(--accent2)]">{c.predicate}</span>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            {c.history.map((h, k) => (
              <div key={k} className="flex items-center gap-2">
                <span className={`px-2.5 py-1 rounded-lg text-[12.5px] border
                  ${h.current ? "border-[var(--good)] text-[var(--good)] bg-[rgba(74,222,128,.1)]"
                              : "border-[var(--line)] text-[var(--dim)] line-through"}`}
                  title={h.valid_from ? `${t("from_word")} ${tShort(h.valid_from)}` : ""}>
                  {h.object}
                </span>
                {k < c.history.length - 1 && <ArrowRight size={13} className="text-[var(--dim2)]" />}
              </div>
            ))}
          </div>
        </div>
      )) : <div className="text-[var(--dim)] card-surface text-center py-8">{t("no_contradictions")}</div>}

      <div className="flex items-center gap-2 mt-7 mb-2.5">
        <div className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px]">{t("changelog")}</div>
        <div className="ml-auto flex gap-1">
          {RANGES.map(([l, d]) => (
            <button key={l} onClick={() => setDays(d)}
              className={`px-2.5 py-1 rounded-lg border text-[12px] ${days === d ? "bg-[var(--panel2)] text-[var(--txt)] border-[var(--line)]" : "border-[var(--line)] text-[var(--dim)]"}`}>{l}</button>
          ))}
        </div>
      </div>
      {diff.length ? diff.slice(0, 80).map((d, i) => (
        <div key={i} className="flex items-center gap-3 px-3 py-2 border-b border-[var(--line)]/60">
          <span className="text-[var(--dim2)] text-[11px] tabular-nums w-[78px] flex-none">{tShort(d.created_at)?.slice(0, 10)}</span>
          <LayerPill layer={d.layer} />
          <span className="text-[13.5px] truncate">{d.content}</span>
          {d.namespace && <span className="ml-auto text-[var(--dim2)] text-[11px] flex-none">{d.namespace}</span>}
        </div>
      )) : <div className="text-[var(--dim)] card-surface text-center py-8">{t("nothing_window")}</div>}
    </div>
  );
}
