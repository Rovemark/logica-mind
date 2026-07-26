import { useEffect, useState } from "react";
import { ArrowLeft, Brain, Boxes, Database, Layers, ListOrdered, Sparkles, Check } from "lucide-react";
import { api, type IntegrationsData, type IntegrationOption } from "../api";
import { useI18n } from "../i18n";

type Status = "active" | "ready" | "setkey" | "install" | "available";

function statusOf(o: IntegrationOption, activeId?: string | null): Status {
  if (activeId && o.id === activeId) return "active";
  if (o.detected && o.installed) return "ready";
  if (o.env && !o.detected) return "setkey";
  if (!o.installed) return "install";
  return "available";
}

export default function Integrations({ onBack, embedded }: { onBack?: () => void; embedded?: boolean }) {
  const { t } = useI18n();
  const [data, setData] = useState<IntegrationsData | null>(null);
  const [err, setErr] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = () => api.integrations().then(setData).catch(() => setErr(true));
  useEffect(() => { refresh(); }, []);

  // pick which LLM serves the whole mind. Clicking the active one turns it off
  // (keyless). Applies live and persists across restart.
  const pickLLM = async (id: string) => {
    const activeId = data?.active.llm.available ? data.active.llm.id : null;
    const target = id === activeId ? "none" : id;
    setBusy(id);
    try {
      const r = await api.setLLM(target);
      if (!r.ok && r.error) alert(r.error);
    } catch { /* fail-soft */ }
    finally { await refresh(); setBusy(null); }
  };

  return (
    <div className="fadein">
      {!embedded && (
        <>
          <div className="flex items-center gap-2 mb-1">
            {onBack && <button onClick={onBack} className="text-[var(--dim)] hover:text-[var(--txt)] -ml-1 p-1"><ArrowLeft size={17} /></button>}
            <h3 className="m-0 text-[16px] font-bold">{t("integrations")}</h3>
          </div>
          <div className="text-[12px] text-[var(--dim2)] mb-4 ml-6">{t("integrations_sub")}</div>
        </>
      )}

      {err && <div className="text-[var(--dim)] text-center py-6 text-[12.5px]">—</div>}
      {data && (
        <>
          {/* active stack */}
          <div className="text-[var(--dim2)] text-[11px] uppercase tracking-[.7px] mb-2">{t("intg_active")}</div>
          <div className="grid grid-cols-2 gap-2 mb-5 max-[380px]:grid-cols-1">
            <ActiveCard icon={Brain} label={t("intg_llm")}
              value={data.active.llm.available ? (data.active.llm.model || data.active.llm.id) : t("intg_offline")}
              ok={data.active.llm.available} />
            <ActiveCard icon={Layers} label={t("intg_embedder")}
              value={`${data.active.embedder.model || data.active.embedder.id}${data.active.embedder.dims ? ` · ${data.active.embedder.dims}${t("intg_dims")}` : ""}`}
              ok />
            <ActiveCard icon={Database} label={t("intg_store")}
              value={data.active.store.backends.length
                ? `${t("intg_redundant")} ${data.active.store.backends.join(", ")}`
                : data.active.store.id}
              ok />
            <ActiveCard icon={ListOrdered} label={t("intg_reranker")}
              value={data.active.reranker || t("intg_none")} ok={!!data.active.reranker} />
          </div>

          <Group title={t("intg_llms")} icon={Sparkles} options={data.available.llm} activeId={data.active.llm.available ? data.active.llm.id : null} t={t} onPick={pickLLM} busy={busy} />
          <Group title={t("intg_embedders")} icon={Layers} options={data.available.embedders} activeId={data.active.embedder.id} t={t} />
          <Group title={t("intg_rerankers")} icon={ListOrdered} options={data.available.rerankers} activeId={data.active.reranker} t={t} />
          <Group title={t("intg_stores")} icon={Boxes} options={data.available.stores} activeId={data.active.store.id} activeBackends={data.active.store.backends} t={t} />
        </>
      )}

      {!embedded && onBack && (
        <button onClick={onBack}
          className="mt-3 w-full py-2.5 rounded-[10px] text-[13px] font-semibold text-white bg-gradient-to-br from-[var(--accent)] to-[var(--accent2)]">{t("done")}</button>
      )}
    </div>
  );
}

function ActiveCard({ icon: Icon, label, value, ok }: { icon: any; label: string; value: string; ok?: boolean }) {
  return (
    <div className="card-surface px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-[10.5px] uppercase tracking-[.6px] text-[var(--dim2)] mb-1">
        <Icon size={12} /> {label}
      </div>
      <div className={`text-[12.5px] font-medium truncate ${ok ? "text-[var(--txt)]" : "text-[var(--dim2)]"}`}>{value}</div>
    </div>
  );
}

function Group({ title, icon: Icon, options, activeId, activeBackends, t, onPick, busy }: {
  title: string; icon: any; options: IntegrationOption[]; activeId?: string | null; activeBackends?: string[];
  t: (k: any, v?: any) => string; onPick?: (id: string) => void; busy?: string | null;
}) {
  return (
    <div className="mb-4">
      <div className="flex items-center gap-1.5 text-[var(--dim2)] text-[11px] uppercase tracking-[.7px] mb-2">
        <Icon size={12} /> {title}
        {onPick && <span className="ml-auto normal-case tracking-normal text-[10px] text-[var(--dim2)] font-normal">{t("intg_pick_hint")}</span>}
      </div>
      <div className="flex flex-col gap-1.5">
        {options.map((o) => {
          const isActive = (activeId && o.id === activeId) || (activeBackends && activeBackends.includes(o.id));
          const s: Status = isActive ? "active" : statusOf(o, null);
          const loading = busy === o.id;
          const inner = (
            <>
              <div className="min-w-0 flex-1 text-left">
                <div className="flex items-center gap-2">
                  <span className="text-[12.5px] font-semibold truncate">{o.label}</span>
                  {o.model && <span className="text-[10.5px] text-[var(--dim2)] truncate">{o.model}</span>}
                </div>
                {o.blurb && <div className="text-[11px] text-[var(--dim2)] leading-snug mt-0.5">{o.blurb}</div>}
              </div>
              {loading ? <span className="text-[10px] text-[var(--dim2)]">…</span> : <Badge s={s} env={o.env} t={t} />}
            </>
          );
          return onPick ? (
            <button key={o.id} onClick={() => !loading && onPick(o.id)} disabled={loading}
              title={isActive ? t("intg_click_off") : t("intg_click_use")}
              className={`card-surface px-3 py-2 flex items-center gap-2.5 w-full text-left transition-colors hover:border-[var(--accent)] ${isActive ? "border-[var(--good)]" : ""} ${loading ? "opacity-60" : "cursor-pointer"}`}>
              {inner}
            </button>
          ) : (
            <div key={o.id} className="card-surface px-3 py-2 flex items-center gap-2.5">{inner}</div>
          );
        })}
      </div>
    </div>
  );
}

function Badge({ s, env, t }: { s: Status; env?: string | null; t: (k: any, v?: any) => string }) {
  const map: Record<Status, { c: string; label: string }> = {
    active: { c: "var(--good)", label: t("st_active") },
    ready: { c: "var(--accent)", label: t("st_ready") },
    setkey: { c: "var(--gold)", label: env ? t("st_setkey", { env }) : t("st_available") },
    install: { c: "var(--dim2)", label: t("st_install") },
    available: { c: "var(--dim2)", label: t("st_available") },
  };
  const { c, label } = map[s];
  return (
    <span className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-wide px-2 py-1 rounded-full flex-none"
      style={{ color: c, background: `color-mix(in srgb, ${c} 14%, transparent)` }}>
      {s === "active" && <Check size={10} />} {label}
    </span>
  );
}
