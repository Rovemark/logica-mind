import { useEffect, useMemo, useState } from "react";
import { CheckCircle2 } from "lucide-react";
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

      <div className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px] mb-1">{t("contradictions")}</div>
      <div className="text-[12px] text-[var(--dim2)] mb-3">{t("contras_desc")}</div>
      {contras.length ? contras.map((c, i) => {
        const current = c.history.find((h) => h.current);
        const past = c.history.filter((h) => !h.current);
        return (
          <div key={i} className="card-surface px-4 py-3.5 mb-2.5">
            <div className="flex items-baseline gap-2 mb-3">
              <span className="text-[13.5px] text-[var(--txt)] font-semibold">{c.subject}</span>
              <span className="text-[12.5px] text-[var(--accent2)]">{c.predicate}</span>
            </div>
            {/* what's true now — stands out */}
            {current && (
              <div className="flex items-center gap-2.5 mb-2.5">
                <CheckCircle2 size={15} className="text-[var(--good)] flex-none" />
                <span className="px-2.5 py-1 rounded-lg text-[13px] font-semibold border border-[var(--good)]/50 text-[var(--good)] bg-[var(--good)]/10">
                  {current.object}
                </span>
                <span className="text-[11px] text-[var(--dim2)]">
                  {t("current_now")}{current.valid_from ? ` · ${t("since_word")} ${tShort(current.valid_from)?.slice(0, 10)}` : ""}
                </span>
              </div>
            )}
            {/* superseded — invalidated, not deleted */}
            {past.map((h, k) => (
              <div key={k} className="flex items-center gap-2.5 ml-[26px] mb-1">
                <span className="px-2.5 py-1 rounded-lg text-[12px] border border-[var(--line)] text-[var(--dim2)] line-through decoration-[var(--warn)]/70">
                  {h.object}
                </span>
                <span className="text-[10.5px] text-[var(--dim2)]">
                  {h.valid_to ? `${t("until_word")} ${tShort(h.valid_to)?.slice(0, 10)}` : t("superseded")}
                </span>
              </div>
            ))}
          </div>
        );
      }) : <div className="text-[var(--dim)] card-surface text-center py-8">{t("no_contradictions")}</div>}

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
