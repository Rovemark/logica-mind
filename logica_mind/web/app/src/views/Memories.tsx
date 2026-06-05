import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { api, LAYERS, type Memory } from "../api";
import MemoryCard from "../components/MemoryCard";
import Pager, { paginate } from "../components/Pager";
import { useI18n } from "../i18n";
import type { MemFilter } from "../navctx";

const PAGE = 20;

export default function Memories({ ns, focus, onChanged, filter }: { ns: string; focus?: { id: string; n: number } | null; onChanged?: () => void; filter?: MemFilter | null; [k: string]: any }) {
  const { t } = useI18n();
  const [layer, setLayer] = useState("");
  const [mems, setMems] = useState<Memory[]>([]);
  const [hl, setHl] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [memF, setMemF] = useState<MemFilter | null>(filter ?? null);

  async function del(m: Memory) {
    await api.forget(m.namespace, m.id);
    setMems((ms) => ms.filter((x) => x.id !== m.id));   // optimistic
    onChanged?.();                                        // refresh sidebar counts
  }

  useEffect(() => {
    api.memories(ns, layer || undefined, memF?.dimension, memF?.category).then((d) => setMems(d.memories)).catch(() => setMems([]));
    setPage(1);
  }, [ns, layer, memF]);

  // when sent here to open a specific memory, drop any layer filter so it shows
  useEffect(() => { if (focus) setLayer(""); /* eslint-disable-next-line */ }, [focus?.n, focus?.id]);

  // scroll to + highlight the focused memory — jump to its page first if needed
  useEffect(() => {
    if (!focus) return;
    const idx = mems.findIndex((m) => m.id === focus.id);
    if (idx < 0) return;
    const target = Math.floor(idx / PAGE) + 1;
    if (target !== page) { setPage(target); return; }     // re-runs after page change
    const el = document.getElementById(`mc-${focus.id}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    setHl(focus.id);
    const tm = setTimeout(() => setHl(null), 2200);
    return () => clearTimeout(tm);
    /* eslint-disable-next-line */
  }, [focus?.id, focus?.n, mems, page]);

  const { pages, page: cp, slice } = paginate(mems, page, PAGE);

  const chips: [string, string][] = [
    ["", t("all_word")],
    ...LAYERS.map((l) => [l, t(`layer_${l}` as any) || (l[0].toUpperCase() + l.slice(1))] as [string, string]),
  ];

  return (
    <div className="fadein">
      <h2 className="m-0 mb-4 text-[18px] font-bold tracking-tight">{t("memories")}</h2>
      <div className="flex gap-[7px] mb-4 flex-wrap">
        {chips.map(([k, l]) => (
          <button key={k} onClick={() => setLayer(k)}
            className={`px-[13px] py-1.5 rounded-[9px] border text-[12.5px]
              ${layer === k ? "bg-[var(--panel2)] text-[var(--txt)] border-[var(--line)]"
                            : "border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)]"}`}>{l}</button>
        ))}
        {memF && (
          <span className="flex items-center gap-1.5 px-[11px] py-1.5 rounded-[9px] text-[12.5px] font-medium bg-[var(--accent)]/12 text-[var(--accent)] border border-[var(--accent)]/40">
            {memF.label || memF.category || memF.dimension}
            <button onClick={() => setMemF(null)} className="hover:opacity-70"><X size={13} /></button>
          </span>
        )}
      </div>
      {mems.length ? (<>
        {slice.map((m) => <MemoryCard key={m.id} m={m} highlight={hl === m.id} onDelete={() => del(m)} />)}
        <Pager page={cp} pages={pages} onPage={setPage} />
      </>) : <div className="text-[var(--dim)] text-center py-12">{t("nothing_here")}</div>}
    </div>
  );
}
