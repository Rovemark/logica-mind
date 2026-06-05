import { useEffect, useRef, useState } from "react";
import { Hexagon, Clock, Timer, RotateCw, Maximize2, Palette, X } from "lucide-react";
import { api, tShort, type GraphData } from "../api";
import GraphCanvas, { type GraphHandle } from "../components/GraphCanvas";
import NodeDetail from "../components/NodeDetail";
import { useI18n } from "../i18n";

export default function GraphView({ ns, colorFor, onOpenMemory }: { ns: string; colorFor: (n: string) => string; onOpenMemory?: (m: any) => void }) {
  const { t } = useI18n();
  const [data, setData] = useState<GraphData>({ nodes: [], links: [] });
  const [history, setHistory] = useState(true);
  const [communities, setCommunities] = useState(false);
  const [at, setAt] = useState<string | null>(null);
  const [range, setRange] = useState<{ min: string; max: string } | null>(null);
  const [scrub, setScrub] = useState(false);
  const [showLegend, setShowLegend] = useState(false);
  const [picked, setPicked] = useState<string | null>(null);
  const gref = useRef<GraphHandle>(null);

  useEffect(() => {
    api.graph(ns, history, at).then(setData).catch(() => setData({ nodes: [], links: [] }));
  }, [ns, history, at]);

  // reset detail/scrubber when switching namespace
  useEffect(() => { setPicked(null); setScrub(false); setAt(null); }, [ns]);

  async function toggleScrub() {
    if (scrub) { setScrub(false); setAt(null); return; }
    const tr = await api.timerange(ns);
    if (!tr.max || !tr.min) return;
    setRange({ min: tr.min, max: tr.max }); setScrub(true);
  }

  const Btn = ({ on, onClick, icon: Icon, children }: any) => (
    <button onClick={onClick}
      className={`glass border rounded-[9px] px-3 py-[7px] text-[12px] inline-flex items-center gap-1.5
        ${on ? "text-[var(--gold)] border-[var(--gold)]" : "text-[var(--dim)] border-[var(--line)] hover:text-[var(--txt)]"}`}>
      <Icon size={13} /> {children}
    </button>
  );

  const legendNs = (() => {
    const s = new Set<string>();
    data.nodes.forEach((n) => (n.namespaces || []).forEach((x) => s.add(x)));
    return [...s].slice(0, 8);
  })();

  return (
    <div className="fadein">
      <h2 className="m-0 mb-4 text-[18px] font-bold tracking-tight">{t("graph")}</h2>
      <div className="relative" style={{ height: "calc(100vh - 200px)", minHeight: 420 }}>
        <div className="absolute top-3 left-3.5 text-[var(--dim2)] text-[11.5px] z-[3]">
          {data.nodes.length} {t("graph_entities")} · {data.links.length} {t("relations")}
          {at && <span className="text-[var(--gold)]"> · {t("graph_as_of")} {tShort(at)}</span>}
        </div>
        <div className="absolute top-3 right-3 flex gap-1.5 z-[3] flex-wrap justify-end max-w-[70%]">
          <Btn on={communities} onClick={() => setCommunities((v) => !v)} icon={Hexagon}>{t("graph_communities")}</Btn>
          <Btn on={history} onClick={() => setHistory((v) => !v)} icon={Clock}>{t("graph_history")}</Btn>
          <Btn on={scrub} onClick={toggleScrub} icon={Timer}>{t("graph_time")}</Btn>
          <Btn onClick={() => gref.current?.reheat()} icon={RotateCw}>{t("graph_shake")}</Btn>
          <Btn onClick={() => gref.current?.fit()} icon={Maximize2}>{t("graph_fit")}</Btn>
        </div>

        {data.nodes.length === 0 ? (
          <div className="w-full h-full grid place-items-center text-[var(--dim)] card-surface">{t("graph_empty")}</div>
        ) : (
          <GraphCanvas ref={gref} data={data} communities={communities} colorFor={colorFor} onPick={setPicked} />
        )}

        {picked && (
          <NodeDetail ns={ns} name={picked} onClose={() => setPicked(null)}
            onOpenMemory={(m) => onOpenMemory?.(m)} onPickEntity={(n) => setPicked(n)} />
        )}

        {/* legend — collapsible (a panel that opens on click), so a graph with many
            namespaces doesn't get a wall of swatches stuck on screen */}
        {!scrub && data.nodes.length > 0 && (
          <div className="absolute bottom-3 left-3.5 z-[3]">
            {showLegend ? (
              <div className="glass border border-[var(--line)] rounded-[12px] p-3 text-[11.5px] w-[230px] max-h-[260px] overflow-y-auto shadow-[var(--shadow)]">
                <div className="flex items-center mb-2">
                  <span className="text-[var(--dim2)] text-[10px] uppercase tracking-[.7px]">{t("graph_legend")}</span>
                  <button onClick={() => setShowLegend(false)} className="ml-auto text-[var(--dim)] hover:text-[var(--txt)]"><X size={13} /></button>
                </div>
                {communities ? (
                  <div className="flex items-center gap-1.5 text-[var(--dim)]"><Hexagon size={12} /> {t("colored_by_community")}</div>

                ) : (
                  <div className="flex flex-col gap-1.5">
                    {legendNs.map((n) => (
                      <span key={n} className="inline-flex items-center gap-2 text-[var(--dim)]">
                        <span className="w-2.5 h-2.5 rounded-full flex-none" style={{ background: colorFor(n) }} />
                        <span className="truncate">{n}</span>
                      </span>
                    ))}
                    <span className="inline-flex items-center gap-2 text-[var(--dim)] mt-1"><span className="w-2.5 h-2.5 rounded-full bg-[var(--gold)] flex-none" />{t("shared_entity")}</span>
                    <span className="inline-flex items-center gap-2 text-[var(--dim)]"><span className="w-3 border-t border-dashed border-[var(--dim2)] flex-none" />{t("superseded")}</span>
                  </div>
                )}
              </div>
            ) : (
              <button onClick={() => setShowLegend(true)}
                className="glass border border-[var(--line)] rounded-[9px] px-2.5 py-[7px] text-[12px] text-[var(--dim)] hover:text-[var(--txt)] inline-flex items-center gap-1.5">
                <Palette size={13} /> {t("graph_legend")}
              </button>
            )}
          </div>
        )}

        {scrub && range && (
          <div className="absolute left-3.5 right-3.5 bottom-3 glass border border-[var(--line)] rounded-[11px] px-3.5 py-2.5 flex items-center gap-3.5 z-[3]">
            <span className="text-[11.5px] text-[var(--dim)] tabular-nums whitespace-nowrap">{tShort(range.min)}</span>
            <input type="range" className="flex-1 accent-[var(--accent)]"
              min={Date.parse(range.min.replace(" ", "T"))} max={Date.parse(range.max.replace(" ", "T"))} step={1000}
              defaultValue={Date.parse(range.max.replace(" ", "T"))}
              onChange={(e) => setAt(new Date(+e.target.value).toISOString().replace(/\.\d+Z$/, "Z"))} />
            <span className="text-[11.5px] text-[var(--dim)] whitespace-nowrap">
              {t("graph_as_of")}: <span className="text-[var(--gold)] font-semibold">{at ? tShort(at) : tShort(range.max)}</span>
            </span>
          </div>
        )}
      </div>
      <div className="text-[var(--dim2)] text-[12px] mt-2.5 max-[820px]:hidden">
        {t("graph_tip")}
      </div>
    </div>
  );
}
