import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, CalendarDays } from "lucide-react";
import { api, type Memory, type Stats } from "../api";
import MemoryCard from "../components/MemoryCard";
import Pager, { paginate } from "../components/Pager";
import { useI18n } from "../i18n";

const pad = (n: number) => String(n).padStart(2, "0");
const key = (y: number, m: number, d: number) => `${y}-${pad(m + 1)}-${pad(d)}`;

// Obsidian-style calendar: a month heatmap of daily memory activity; pick a day
// to read that day's memories in the pane beside it (always visible).
export default function Calendar({ ns }: { ns: string }) {
  const { t } = useI18n();
  const WD = t("weekdays").split(",");
  const MO = t("months").split(",");
  const [days, setDays] = useState<Record<string, Stats>>({});
  const [cur, setCur] = useState<{ y: number; m: number }>(() => { const t = new Date(); return { y: t.getFullYear(), m: t.getMonth() }; });
  const [sel, setSel] = useState<string | null>(null);
  const [dayMems, setDayMems] = useState<Memory[]>([]);
  const [mode, setMode] = useState<"month" | "week">("month");
  const [weekAnchor, setWeekAnchor] = useState<Date>(() => new Date());
  const [page, setPage] = useState(1);
  const paneRef = useRef<HTMLDivElement>(null);
  useEffect(() => { setPage(1); }, [sel]);
  const dpg = paginate(dayMems, page, 15);

  useEffect(() => {
    api.calendar(ns).then((d) => {
      setDays(d.days || {});
      const ks = Object.keys(d.days || {}).sort();
      if (ks.length) {
        const last = ks[ks.length - 1];
        const [y, m] = last.split("-").map(Number);
        setCur({ y, m: m - 1 });
        setSel(last);                 // auto-select the most recent day with data
      } else { setSel(null); }
    }).catch(() => { setDays({}); setSel(null); });
  }, [ns]);

  useEffect(() => {
    if (!sel) { setDayMems([]); return; }
    api.day(ns, sel).then((d) => setDayMems(d.memories)).catch(() => setDayMems([]));
    if (window.innerWidth < 900) paneRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [ns, sel]);

  const { cells, max, label } = useMemo(() => {
    const arr: ({ d: number; k: string; n: number } | null)[] = [];
    let mx = 1, label = "";
    if (mode === "week") {
      const a = new Date(weekAnchor); a.setDate(a.getDate() - a.getDay());   // Sunday start
      for (let i = 0; i < 7; i++) {
        const d = new Date(a); d.setDate(a.getDate() + i);
        const k = key(d.getFullYear(), d.getMonth(), d.getDate());
        const n = days[k]?.total || 0; mx = Math.max(mx, n);
        arr.push({ d: d.getDate(), k, n });
      }
      const end = new Date(a); end.setDate(a.getDate() + 6);
      label = `${MO[a.getMonth()].slice(0, 3)} ${a.getDate()} – ${MO[end.getMonth()].slice(0, 3)} ${end.getDate()}`;
    } else {
      const first = new Date(cur.y, cur.m, 1).getDay();
      const ndays = new Date(cur.y, cur.m + 1, 0).getDate();
      for (let d = 1; d <= ndays; d++) mx = Math.max(mx, days[key(cur.y, cur.m, d)]?.total || 0);
      for (let i = 0; i < first; i++) arr.push(null);
      for (let d = 1; d <= ndays; d++) { const k = key(cur.y, cur.m, d); arr.push({ d, k, n: days[k]?.total || 0 }); }
      label = `${MO[cur.m]} ${cur.y}`;
    }
    return { cells: arr, max: mx, label };
  }, [cur, days, mode, weekAnchor]);

  const today = new Date();
  const todayKey = key(today.getFullYear(), today.getMonth(), today.getDate());
  const move = (delta: number) => {
    if (mode === "week") { const d = new Date(weekAnchor); d.setDate(d.getDate() + delta * 7); setWeekAnchor(d); }
    else { const d = new Date(cur.y, cur.m + delta, 1); setCur({ y: d.getFullYear(), m: d.getMonth() }); }
  };
  const monthTotal = cells.reduce((a, c) => a + (c?.n || 0), 0);

  return (
    <div className="fadein flex gap-4 max-[900px]:flex-col">
      {/* calendar */}
      <div className="w-[470px] max-w-full flex-none">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <h2 className="m-0 text-[18px] font-bold tracking-tight">{t("calendar")}</h2>
          <div className="ml-auto flex items-center gap-1 rounded-[9px] border border-[var(--line)] p-0.5">
            {(["month", "week"] as const).map((md) => (
              <button key={md} onClick={() => { if (md === "week" && sel) setWeekAnchor(new Date(sel + "T12:00:00")); setMode(md); }}
                className={`px-2.5 py-1 rounded-[7px] text-[12px] ${mode === md ? "bg-[var(--panel2)] text-[var(--txt)]" : "text-[var(--dim)]"}`}>{t(md)}</button>
            ))}
          </div>
          <div className="flex items-center gap-1 w-full justify-end">
            <button onClick={() => move(-1)} className="w-8 h-8 grid place-items-center rounded-[9px] border border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)]"><ChevronLeft size={16} /></button>
            <div className="min-w-[150px] text-center font-semibold text-[14px]">{label}</div>
            <button onClick={() => move(1)} className="w-8 h-8 grid place-items-center rounded-[9px] border border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)]"><ChevronRight size={16} /></button>
          </div>
        </div>

        <div className="card-surface p-3.5">
          <div className="grid grid-cols-7 gap-1.5 mb-1.5">
            {WD.map((w) => <div key={w} className="text-center text-[var(--dim2)] text-[11px] font-semibold py-1">{w}</div>)}
          </div>
          <div className="grid grid-cols-7 gap-1.5">
            {cells.map((c, i) => {
              if (!c) return <div key={i} />;
              const heat = c.n ? 0.12 + 0.62 * (c.n / max) : 0;
              const isSel = sel === c.k, isToday = c.k === todayKey;
              return (
                <button key={i} onClick={() => setSel(c.k)}
                  className={`relative aspect-square rounded-[10px] border flex flex-col items-center justify-center transition
                    ${isSel ? "border-[var(--accent)] ring-2 ring-[var(--accent)]/40" : isToday ? "border-[var(--gold)]" : "border-[var(--line)]"}
                    ${c.n ? "hover:brightness-125" : "opacity-60 hover:opacity-100"}`}
                  style={{ background: c.n ? `rgba(124,156,255,${heat})` : "var(--panel2)" }}
                  title={c.n ? `${c.n} ${t("memories_word")}` : t("no_memories")}>
                  <span className={`text-[13px] tabular-nums ${c.n ? "text-[var(--txt)] font-semibold" : "text-[var(--dim2)]"}`}>{c.d}</span>
                  {c.n > 0 && <span className="text-[9.5px] text-[var(--dim)] tabular-nums leading-none mt-0.5">{c.n}</span>}
                </button>
              );
            })}
          </div>
          <div className="flex items-center gap-2 mt-3 text-[var(--dim2)] text-[11.5px]">
            <CalendarDays className="text-[var(--accent)]" size={13} />
            {monthTotal} {t("memories_word")} · {t("busier")}
          </div>
        </div>
        <button onClick={() => { setWeekAnchor(new Date()); setCur({ y: today.getFullYear(), m: today.getMonth() }); }}
          className="mt-2.5 px-3 h-8 rounded-[9px] border border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)] text-[12.5px]">{t("jump_today")}</button>
      </div>

      {/* day pane (always visible) */}
      <div ref={paneRef} className="flex-1 min-w-0">
        <div className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px] mb-2.5 h-[26px] flex items-center">
          {sel ? `${t("memories_on")} ${sel} · ${dayMems.length}` : t("pick_day")}
        </div>
        {sel ? (
          dayMems.length ? (<>{dpg.slice.map((m) => <MemoryCard key={m.id} m={m} />)}<Pager page={dpg.page} pages={dpg.pages} onPage={setPage} /></>)
            : <div className="text-[var(--dim)] card-surface text-center py-10">{t("no_memories_day")}</div>
        ) : (
          <div className="text-[var(--dim)] card-surface text-center py-10">{t("select_day")}</div>
        )}
      </div>
    </div>
  );
}
