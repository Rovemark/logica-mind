import { useEffect, useState } from "react";
import { ArrowRight, Users } from "lucide-react";
import { api, type PeerPair } from "../api";
import Pager, { paginate } from "../components/Pager";
import Markdown from "../components/Markdown";
import { useI18n } from "../i18n";

// Multi-perspective: what one peer believes about another (directional).
export default function Peers({ ns }: { ns: string }) {
  const { t } = useI18n();
  const [pairs, setPairs] = useState<PeerPair[]>([]);
  const [sel, setSel] = useState<PeerPair | null>(null);
  const [card, setCard] = useState<string>("");
  const [page, setPage] = useState(1);

  useEffect(() => {
    api.peers(ns).then((d) => { setPairs(d.peers || []); setSel(d.peers?.[0] || null); }).catch(() => setPairs([]));
    setPage(1);
  }, [ns]);
  const ppg = paginate(pairs, page, 12);

  useEffect(() => {
    if (!sel) { setCard(""); return; }
    api.peerCard(sel.namespace, sel.observer, sel.observed).then((d) => setCard(d.card || "")).catch(() => setCard(""));
  }, [sel]);

  const lines = card.split("\n").map((l) => l.replace(/^[-•]\s*/, "").trim()).filter(Boolean);

  return (
    <div className="fadein flex gap-4 max-[900px]:flex-col">
      <div className="w-[340px] max-w-full flex-none">
        <h2 className="m-0 mb-4 text-[18px] font-bold tracking-tight">{t("peers")}</h2>
        {pairs.length ? (<>{ppg.slice.map((p, i) => {
          const on = sel && sel.observer === p.observer && sel.observed === p.observed && sel.namespace === p.namespace;
          return (
            <button key={i} onClick={() => setSel(p)}
              className={`w-full text-left card-surface px-3.5 py-3 mb-2 flex items-center gap-2 transition
                ${on ? "border-[var(--accent)] ring-1 ring-[var(--accent)]/40" : "hover:border-[var(--accent)]/50"}`}>
              <span className="font-semibold text-[var(--txt)]">{p.observer}</span>
              <ArrowRight size={13} className="text-[var(--accent2)]" />
              <span className="font-semibold text-[var(--txt)]">{p.observed}</span>
              <span className="ml-auto text-[var(--dim2)] text-[11px] tabular-nums">{p.count}</span>
              <span className="text-[var(--dim2)] text-[11px] bg-[var(--panel2)] border border-[var(--line)] px-1.5 rounded">{p.namespace}</span>
            </button>
          );
        })}<Pager page={ppg.page} pages={ppg.pages} onPage={setPage} /></>) : <div className="text-[var(--dim)] card-surface text-center py-10">{t("no_peer_obs")}</div>}
      </div>

      <div className="flex-1 min-w-0">
        <div className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px] mb-2.5 h-[26px] flex items-center gap-2">
          <Users size={14} /> {sel ? t("believes_about", { a: sel.observer, b: sel.observed }) : t("pick_peer")}
        </div>
        {sel ? (
          lines.length ? (
            <div className="rounded-[13px] p-3 panel-grad">
              {lines.map((l, i) => (
                <div key={i} className="flex items-start gap-2.5 px-2 py-2 rounded-lg hover:bg-white/[0.03]">
                  <span className="text-[var(--accent2)] mt-1.5 text-[8px]">●</span>
                  <Markdown text={l} className="text-[14px] leading-relaxed min-w-0" />
                </div>
              ))}
            </div>
          ) : <div className="text-[var(--dim)] card-surface text-center py-10">{t("no_peer_card")}</div>
        ) : (
          <div className="text-[var(--dim)] card-surface text-center py-10">{t("select_peer_rel")}</div>
        )}
      </div>
    </div>
  );
}
