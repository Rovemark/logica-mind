import { useRef, useState } from "react";
import { Moon, Sun, Monitor, Check, Download, Upload, Trash2, AlertTriangle, SlidersHorizontal, Boxes, Database } from "lucide-react";
import { useI18n, LANGS, type Lang } from "../i18n";
import { getTheme, setTheme, type Theme } from "../theme";
import { api, ALL, LAYERS, type Layer } from "../api";
import Integrations from "./Integrations";

export function getAnim(): boolean {
  return localStorage.getItem("lm-anim") !== "off";
}

type Tab = "general" | "integrations" | "data";

// Settings is a full page (not a modal): a left rail of sections + content.
export default function Settings({ ns }: { ns: string }) {
  const { t, lang, setLang } = useI18n();
  const [tab, setTab] = useState<Tab>("general");
  const [theme, setTh] = useState<Theme>(getTheme());
  const [anim, setAnim] = useState<boolean>(getAnim());
  const [clearLayer, setClearLayer] = useState<Layer | "stale" | "">("");
  const [importMsg, setImportMsg] = useState("");
  const [importing, setImporting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [confirmText, setConfirmText] = useState("");
  const [clearing, setClearing] = useState(false);
  const [clearMsg, setClearMsg] = useState("");

  function download(name: string, data: any) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name; a.click(); URL.revokeObjectURL(a.href);
  }
  async function exportJson() { download(`logica-mind-${ns === ALL ? "all" : ns}.json`, await api.exportNs(ns)); }
  async function exportBundle() { download(`logica-mind-bundle-${ns === ALL ? "all" : ns}.json`, await api.bundle(ns)); }

  async function importBundle(file: File) {
    setImporting(true); setImportMsg("");
    try {
      const bundle = JSON.parse(await file.text());
      const res = await api.importBundle(ns, bundle);
      setImportMsg(`${t("import_success")} · ${res.imported ?? 0}`);
    } catch { setImportMsg(t("import_error")); }
    setImporting(false);
    if (fileRef.current) fileRef.current.value = "";
  }

  const CONFIRM_WORD = lang === "pt" ? "LIMPAR" : lang === "es" ? "BORRAR" : "CLEAR";

  async function doClear() {
    if (confirmText.trim().toUpperCase() !== CONFIRM_WORD) return;
    setClearing(true); setClearMsg("");
    try {
      const opts = clearLayer === "stale" ? { older_than_days: 60 }
        : clearLayer ? { layer: clearLayer } : { purge_all: true };
      const res = await api.clearMemories(ns, opts);
      const n = res.deleted === -1 ? t("all_word") : res.deleted;
      setClearMsg(`${t("cleared")} · ${n} ${t("entries_word")}`);
    } catch { setClearMsg(t("clear_error")); }
    setClearing(false); setConfirmText(""); setClearLayer("");
  }

  const pickTheme = (v: Theme) => { setTheme(v); setTh(v); };
  const themes: { v: Theme; icon: any; label: string }[] = [
    { v: "dark", icon: Moon, label: t("dark") },
    { v: "light", icon: Sun, label: t("light") },
    { v: "auto", icon: Monitor, label: t("auto") },
  ];
  const TABS: { k: Tab; icon: any; label: string }[] = [
    { k: "general", icon: SlidersHorizontal, label: t("settings_general") },
    { k: "integrations", icon: Boxes, label: t("integrations") },
    { k: "data", icon: Database, label: t("data") },
  ];

  return (
    <div className="fadein max-w-[900px]">
      <h2 className="m-0 mb-5 text-[18px] font-bold tracking-tight">{t("settings")}</h2>
      <div className="grid grid-cols-[190px_1fr] gap-6 max-[720px]:grid-cols-1">
        {/* left rail */}
        <nav className="flex flex-col gap-1 max-[720px]:flex-row max-[720px]:overflow-x-auto">
          {TABS.map(({ k, icon: Icon, label }) => (
            <button key={k} onClick={() => setTab(k)}
              className={`flex items-center gap-2.5 px-3 py-2.5 rounded-[10px] text-[13.5px] font-medium text-left flex-none
                ${tab === k ? "bg-[var(--panel2)] text-[var(--txt)] shadow-[inset_0_0_0_1px_var(--line)]"
                            : "text-[var(--dim)] hover:bg-[var(--panel2)] hover:text-[var(--txt)]"}`}>
              <Icon size={16} /> {label}
            </button>
          ))}
        </nav>

        {/* content */}
        <div className="min-w-0">
          {tab === "general" && (
            <div className="flex flex-col gap-6">
              <Section title={t("appearance")}>
                <div className="text-[13px] mb-1.5">{t("theme")}</div>
                <div className="grid grid-cols-3 gap-2 max-w-[420px]">
                  {themes.map(({ v, icon: Icon, label }) => (
                    <button key={v} onClick={() => pickTheme(v)}
                      className={`flex flex-col items-center gap-1.5 py-3 rounded-[11px] border text-[12.5px] font-medium
                        ${theme === v ? "border-[var(--accent)] text-[var(--accent)] bg-[var(--panel2)]"
                                      : "border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)]"}`}>
                      <Icon size={18} /> {label}
                    </button>
                  ))}
                </div>
              </Section>

              <Section title={t("language")}>
                <div className="grid grid-cols-3 gap-2 max-w-[420px]">
                  {LANGS.map(({ code, label }) => (
                    <button key={code} onClick={() => setLang(code as Lang)}
                      className={`flex items-center justify-center gap-1.5 py-2.5 rounded-[11px] border text-[12.5px] font-medium
                        ${lang === code ? "border-[var(--accent)] text-[var(--accent)] bg-[var(--panel2)]"
                                        : "border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)]"}`}>
                      {lang === code && <Check size={13} />} {label}
                    </button>
                  ))}
                </div>
              </Section>

              <Section title={t("behavior")}>
                <label className="flex items-center gap-3 cursor-pointer">
                  <button onClick={() => { const n = !anim; setAnim(n); localStorage.setItem("lm-anim", n ? "on" : "off"); }}
                    className={`relative w-[42px] h-[24px] rounded-full transition flex-none ${anim ? "bg-[var(--accent)]" : "bg-[var(--panel2)] border border-[var(--line)]"}`}>
                    <span className={`absolute top-[3px] w-[18px] h-[18px] rounded-full bg-white transition-all ${anim ? "left-[21px]" : "left-[3px]"}`} />
                  </button>
                  <span>
                    <span className="text-[13.5px] block">{t("animations")}</span>
                    <span className="text-[var(--dim2)] text-[11.5px]">{t("animations_desc")}</span>
                  </span>
                </label>
              </Section>
            </div>
          )}

          {tab === "integrations" && <Integrations embedded />}

          {tab === "data" && (
            <div className="flex flex-col gap-6">
              <Section title={t("data")}>
                <div className="grid grid-cols-2 gap-2 max-w-[480px] max-[420px]:grid-cols-1">
                  <button onClick={exportJson}
                    className="flex items-center justify-center gap-2 py-2.5 rounded-[10px] border border-[var(--line)] text-[12.5px] text-[var(--dim)] hover:text-[var(--txt)] hover:border-[var(--accent)]/60">
                    <Download size={15} /> {t("export_json")}
                  </button>
                  <button onClick={exportBundle} title={t("portable_bundle_tip")}
                    className="flex items-center justify-center gap-2 py-2.5 rounded-[10px] border border-[var(--line)] text-[12.5px] text-[var(--dim)] hover:text-[var(--txt)] hover:border-[var(--accent)]/60">
                    <Download size={15} /> {t("portable_bundle")}
                  </button>
                </div>
                <input ref={fileRef} type="file" accept=".json" className="hidden"
                  onChange={e => { const f = e.target.files?.[0]; if (f) importBundle(f); }} />
                <button onClick={() => fileRef.current?.click()} disabled={importing}
                  className="mt-2 max-w-[480px] w-full flex items-center justify-center gap-2 py-2.5 rounded-[10px] border border-[var(--line)] text-[12.5px] text-[var(--dim)] hover:text-[var(--txt)] hover:border-[var(--accent)]/60 disabled:opacity-40">
                  <Upload size={15} /> {importing ? t("importing_bundle") : t("import_bundle")}
                </button>
                {importMsg && <div className="text-[11.5px] text-[var(--dim)] mt-1">{importMsg}</div>}
              </Section>

              <Section title={t("danger_zone")} danger>
                <div className="border border-[#fb7185]/30 rounded-[10px] p-3 bg-[#fb718508] max-w-[520px]">
                  <div className="text-[12px] text-[var(--dim)] mb-2">
                    {t("namespace_word")}: <b className="text-[var(--txt)]">{ns === ALL ? t("all_word") : ns}</b>
                  </div>
                  <div className="flex gap-2 mb-2.5 flex-wrap">
                    {([...LAYERS, "stale"] as const).map((l) => (
                      <button key={l} onClick={() => setClearLayer(clearLayer === l ? "" : l)}
                        className={`px-2.5 py-1 rounded-[8px] border text-[11.5px] transition
                          ${clearLayer === l ? "border-[#fb7185] text-[#fb7185] bg-[#fb718518]" : "border-[var(--line)] text-[var(--dim)] hover:border-[#fb7185]/60"}`}>
                        {l === "stale" ? t("stale_60d") : t(`layer_${l}` as any)}
                      </button>
                    ))}
                    <button onClick={() => setClearLayer("")}
                      className={`px-2.5 py-1 rounded-[8px] border text-[11.5px] transition
                        ${!clearLayer ? "border-[#fb7185] text-[#fb7185] bg-[#fb718518]" : "border-[var(--line)] text-[var(--dim)] hover:border-[#fb7185]/60"}`}>
                      {t("clear_all_ns")}
                    </button>
                  </div>
                  <input placeholder={`${t("confirm_clear")} (${CONFIRM_WORD})`}
                    value={confirmText} onChange={e => setConfirmText(e.target.value)}
                    className="w-full bg-[var(--panel2)] border border-[var(--line)] rounded-[8px] px-2.5 py-1.5 text-[12px] text-[var(--txt)] outline-none mb-2" />
                  <button onClick={doClear} disabled={clearing || confirmText.trim().toUpperCase() !== CONFIRM_WORD}
                    className="w-full flex items-center justify-center gap-2 py-2 rounded-[8px] border border-[#fb7185]/60 text-[12.5px] text-[#fb7185] hover:bg-[#fb718520] disabled:opacity-30 disabled:cursor-not-allowed">
                    <Trash2 size={13} /> {clearing ? t("clearing") : t("clear_layer")}
                  </button>
                  {clearMsg && <div className="text-[11.5px] text-[var(--dim)] mt-1.5">{clearMsg}</div>}
                </div>
              </Section>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({ title, children, danger }: { title: string; children: React.ReactNode; danger?: boolean }) {
  return (
    <div>
      <div className={`text-[11px] uppercase tracking-[.7px] mb-2.5 flex items-center gap-1.5 ${danger ? "text-[#fb7185]" : "text-[var(--dim2)]"}`}>
        {danger && <AlertTriangle size={11} />} {title}
      </div>
      {children}
    </div>
  );
}
