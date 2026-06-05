import { useEffect, useState } from "react";
import { Sparkles, X, Trash2 } from "lucide-react";
import { api } from "../api";
import { useI18n } from "../i18n";

// On first launch the dashboard ships empty. This banner offers to LOAD a
// fictional demo dataset, and — once loaded — to KEEP or CLEAR it. The user is
// in control: nothing is seeded automatically, and clearing only removes the
// demo-tagged rows (never anything they added themselves).
export default function DemoBanner({ onChange }: { onChange?: () => void }) {
  const { t } = useI18n();
  const [present, setPresent] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [kept, setKept] = useState(() => localStorage.getItem("lm-demo-kept") === "1");

  const refresh = () => api.demoStatus().then((d) => setPresent(d.present)).catch(() => setPresent(null));
  useEffect(() => { refresh(); }, []);

  async function load() {
    setBusy(true);
    await api.seedDemo().catch(() => {});
    setBusy(false); setKept(false); localStorage.removeItem("lm-demo-kept");
    await refresh(); onChange?.();
  }
  async function clear() {
    setBusy(true);
    await api.clearDemo().catch(() => {});
    setBusy(false); await refresh(); onChange?.();
  }
  function keep() { setKept(true); localStorage.setItem("lm-demo-kept", "1"); }

  if (present === null) return null;

  // empty store → offer to load the demo
  if (!present) {
    return (
      <div className="mx-6 mt-3 max-[820px]:mx-3.5 flex items-center gap-3 rounded-[11px] border border-[var(--line)] bg-[var(--panel2)] px-4 py-2.5">
        <Sparkles size={15} className="text-[var(--accent2)] flex-none" />
        <span className="text-[12.5px] text-[var(--dim)] flex-1">{t("demo_empty")}</span>
        <button onClick={load} disabled={busy}
          className="text-[12px] font-medium px-3 py-1.5 rounded-[8px] bg-[var(--accent)] text-white disabled:opacity-50">
          {busy ? t("demo_loading") : t("demo_load")}
        </button>
      </div>
    );
  }

  // demo loaded and the user already chose to keep it → stay quiet
  if (kept) return null;

  // demo loaded → keep or clear
  return (
    <div className="mx-6 mt-3 max-[820px]:mx-3.5 flex items-center gap-3 rounded-[11px] border border-[var(--gold)]/40 bg-[var(--gold)]/10 px-4 py-2.5">
      <Sparkles size={15} className="text-[var(--gold)] flex-none" />
      <span className="text-[12.5px] text-[var(--txt)] flex-1">{t("demo_loaded")}</span>
      <button onClick={clear} disabled={busy}
        className="inline-flex items-center gap-1.5 text-[12px] px-3 py-1.5 rounded-[8px] border border-[#fb7185]/50 text-[#fb7185] hover:bg-[#fb718515] disabled:opacity-50">
        <Trash2 size={12} /> {busy ? t("clearing") : t("demo_clear")}
      </button>
      <button onClick={keep} title={t("demo_keep")}
        className="inline-flex items-center gap-1.5 text-[12px] px-2.5 py-1.5 rounded-[8px] border border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)]">
        {t("demo_keep")} <X size={12} />
      </button>
    </div>
  );
}
