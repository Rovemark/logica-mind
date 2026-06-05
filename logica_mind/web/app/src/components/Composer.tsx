import { useState } from "react";
import { X, Plus } from "lucide-react";
import { api, ALL } from "../api";
import { useI18n } from "../i18n";

// Write actions from the UI: add a durable memory (remember) or a user
// observation (observe_user) into the selected namespace.
export default function Composer({ ns, onDone }: { ns: string; onDone: () => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<"memory" | "observation">("memory");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const target = ns === ALL ? "default" : ns;

  async function save() {
    const t = text.trim();
    if (!t || busy) return;
    setBusy(true);
    try {
      if (kind === "memory") await api.remember(ns, t);
      else await api.observeUser(ns, t);
      setText(""); setOpen(false); onDone();
    } finally { setBusy(false); }
  }

  return (
    <>
      <button onClick={() => setOpen(true)} title={t("add_memory")}
        className="flex-none w-[38px] h-[38px] grid place-items-center rounded-[10px] text-white
          bg-gradient-to-br from-[var(--accent)] to-[var(--accent2)] shadow-[0_4px_14px_rgba(124,156,255,.35)] hover:brightness-110">
        <Plus size={18} />
      </button>

      {open && (
        <div className="fixed inset-0 z-[60] bg-black/55 backdrop-blur-[2px] grid place-items-center p-3 sm:p-4" onClick={() => setOpen(false)}>
          <div className="w-full max-w-[460px] max-h-[90vh] overflow-y-auto card-surface p-4 fadein" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              <h3 className="m-0 text-[15px] font-bold">{t("add_memory")}</h3>
              <span className="text-[11px] text-[var(--dim)] bg-[var(--panel2)] border border-[var(--line)] px-2 py-[1px] rounded-full">{target}</span>
              <button onClick={() => setOpen(false)} className="ml-auto text-[var(--dim)] hover:text-[var(--txt)]"><X size={16} /></button>
            </div>
            <div className="grid grid-cols-2 gap-1.5 mb-3 max-[380px]:grid-cols-1">
              {(["memory", "observation"] as const).map((k) => (
                <button key={k} onClick={() => setKind(k)}
                  className={`px-3 py-2 rounded-[9px] border text-[12.5px]
                    ${kind === k ? "bg-[var(--panel2)] text-[var(--txt)] border-[var(--accent)]" : "border-[var(--line)] text-[var(--dim)]"}`}>
                  {k === "memory" ? t("durable_memory") : t("user_observation")}
                </button>
              ))}
            </div>
            <textarea value={text} onChange={(e) => setText(e.target.value)} autoFocus rows={4}
              onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") save(); }}
              placeholder={kind === "memory" ? t("memory_ph") : t("observation_ph")}
              className="w-full bg-[var(--bg)] border border-[var(--line)] rounded-[10px] p-3 text-[16px] sm:text-[14px] outline-none
                focus:border-[var(--accent)] resize-none" />
            <div className="flex items-center gap-2 mt-3">
              <span className="text-[var(--dim2)] text-[11px] max-[380px]:hidden">{t("cmd_save")}</span>
              <button onClick={save} disabled={!text.trim() || busy}
                className="ml-auto px-4 py-2 rounded-[9px] text-[13px] font-semibold text-white
                  bg-gradient-to-br from-[var(--accent)] to-[var(--accent2)] disabled:opacity-40">
                {busy ? t("saving") : t("save")}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
