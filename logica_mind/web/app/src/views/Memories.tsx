import { useEffect, useState } from "react";
import { api, LAYERS, type Memory } from "../api";
import MemoryCard from "../components/MemoryCard";
import { useI18n } from "../i18n";

export default function Memories({ ns, focus, onChanged }: { ns: string; focus?: { id: string; n: number } | null; onChanged?: () => void; [k: string]: any }) {
  const { t } = useI18n();
  const [layer, setLayer] = useState("");
  const [mems, setMems] = useState<Memory[]>([]);
  const [hl, setHl] = useState<string | null>(null);

  async function del(m: Memory) {
    await api.forget(m.namespace, m.id);
    setMems((ms) => ms.filter((x) => x.id !== m.id));   // optimistic
    onChanged?.();                                        // refresh sidebar counts
  }

  useEffect(() => {
    api.memories(ns, layer || undefined).then((d) => setMems(d.memories)).catch(() => setMems([]));
  }, [ns, layer]);

  // when sent here to open a specific memory, drop any layer filter so it shows
  useEffect(() => { if (focus) setLayer(""); /* eslint-disable-next-line */ }, [focus?.n]);

  // scroll to + highlight the focused memory once the list is loaded
  useEffect(() => {
    if (!focus) return;
    const el = document.getElementById(`mc-${focus.id}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    setHl(focus.id);
    const t = setTimeout(() => setHl(null), 2200);
    return () => clearTimeout(t);
    /* eslint-disable-next-line */
  }, [focus?.n, mems]);

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
      </div>
      {mems.length ? mems.map((m) => <MemoryCard key={m.id} m={m} highlight={hl === m.id} onDelete={() => del(m)} />)
        : <div className="text-[var(--dim)] text-center py-12">{t("nothing_here")}</div>}
    </div>
  );
}
