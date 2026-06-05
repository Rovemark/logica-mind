import { useRef, useState } from "react";
import { X, Moon, Sun, Monitor, Check, Download, Upload, Trash2, AlertTriangle } from "lucide-react";
import { useI18n, LANGS, type Lang } from "../i18n";
import { getTheme, setTheme, type Theme } from "../theme";
import { api, ALL, LAYERS, type Layer } from "../api";

export function getAnim(): boolean {
  return localStorage.getItem("lm-anim") !== "off";
}

export default function Settings({ ns, onClose }: { ns: string; onClose: () => void }) {
  const { t, lang, setLang } = useI18n();
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
      const text = await file.text();
      const bundle = JSON.parse(text);
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
      const opts = clearLayer === "stale"
        ? { older_than_days: 60 }
        : clearLayer
          ? { layer: clearLayer }
          : { purge_all: true };
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

  return (
    <div className="fixed inset-0 z-[60] bg-black/55 backdrop-blur-[2px] grid place-items-center p-4" onClick={onClose}>
      <div className="w-full max-w-[440px] max-h-[92vh] overflow-y-auto card-surface p-5 fadein" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center mb-4">
          <h3 className="m-0 text-[16px] font-bold">{t("settings")}</h3>
          <button onClick={onClose} className="ml-auto text-[var(--dim)] hover:text-[var(--txt)]"><X size={17} /></button>
        </div>

        {/* theme */}
        <div className="text-[var(--dim2)] text-[11px] uppercase tracking-[.7px] mb-2">{t("appearance")}</div>
        <div className="text-[13px] mb-1.5">{t("theme")}</div>
        <div className="grid grid-cols-3 gap-2 mb-4">
          {themes.map(({ v, icon: Icon, label }) => (
            <button key={v} onClick={() => pickTheme(v)}
              className={`flex flex-col items-center gap-1.5 py-3 rounded-[11px] border text-[12.5px] font-medium
                ${theme === v ? "border-[var(--accent)] text-[var(--accent)] bg-[var(--panel2)]"
                              : "border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)]"}`}>
              <Icon size={18} /> {label}
            </button>
          ))}
        </div>

        {/* language */}
        <div className="text-[13px] mb-1.5">{t("language")}</div>
        <div className="grid grid-cols-3 gap-2 mb-4">
          {LANGS.map(({ code, label }) => (
            <button key={code} onClick={() => setLang(code as Lang)}
              className={`flex items-center justify-center gap-1.5 py-2.5 rounded-[11px] border text-[12.5px] font-medium
                ${lang === code ? "border-[var(--accent)] text-[var(--accent)] bg-[var(--panel2)]"
                                : "border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)]"}`}>
              {lang === code && <Check size={13} />} {label}
            </button>
          ))}
        </div>

        {/* behavior */}
        <div className="text-[var(--dim2)] text-[11px] uppercase tracking-[.7px] mb-2">{t("behavior")}</div>
        <label className="flex items-center gap-3 py-1.5 cursor-pointer">
          <button onClick={() => { const n = !anim; setAnim(n); localStorage.setItem("lm-anim", n ? "on" : "off"); }}
            className={`relative w-[42px] h-[24px] rounded-full transition flex-none ${anim ? "bg-[var(--accent)]" : "bg-[var(--panel2)] border border-[var(--line)]"}`}>
            <span className={`absolute top-[3px] w-[18px] h-[18px] rounded-full bg-white transition-all ${anim ? "left-[21px]" : "left-[3px]"}`} />
          </button>
          <span>
            <span className="text-[13.5px] block">{t("animations")}</span>
            <span className="text-[var(--dim2)] text-[11.5px]">{t("animations_desc")}</span>
          </span>
        </label>

        {/* data */}
        <div className="text-[var(--dim2)] text-[11px] uppercase tracking-[.7px] mt-4 mb-2">{t("data")}</div>
        <div className="grid grid-cols-2 gap-2 max-[380px]:grid-cols-1">
          <button onClick={exportJson}
            className="flex items-center justify-center gap-2 py-2.5 rounded-[10px] border border-[var(--line)]
              text-[12.5px] text-[var(--dim)] hover:text-[var(--txt)] hover:border-[var(--accent)]/60">
            <Download size={15} /> {t("export_json")}
          </button>
          <button onClick={exportBundle} title={t("portable_bundle_tip")}
            className="flex items-center justify-center gap-2 py-2.5 rounded-[10px] border border-[var(--line)]
              text-[12.5px] text-[var(--dim)] hover:text-[var(--txt)] hover:border-[var(--accent)]/60">
            <Download size={15} /> {t("portable_bundle")}
          </button>
        </div>
        {/* import bundle */}
        <input ref={fileRef} type="file" accept=".json" className="hidden"
          onChange={e => { const f = e.target.files?.[0]; if (f) importBundle(f); }} />
        <button onClick={() => fileRef.current?.click()} disabled={importing}
          className="mt-2 w-full flex items-center justify-center gap-2 py-2.5 rounded-[10px] border border-[var(--line)]
            text-[12.5px] text-[var(--dim)] hover:text-[var(--txt)] hover:border-[var(--accent)]/60 disabled:opacity-40">
          <Upload size={15} /> {importing ? t("importing_bundle") : t("import_bundle")}
        </button>
        {importMsg && <div className="text-[11.5px] text-[var(--dim)] text-center mt-1">{importMsg}</div>}

        {/* danger zone */}
        <div className="text-[var(--dim2)] text-[11px] uppercase tracking-[.7px] mt-4 mb-2 flex items-center gap-1.5">
          <AlertTriangle size={11} className="text-[#fb7185]" /> {t("danger_zone")}
        </div>
        <div className="border border-[#fb7185]/30 rounded-[10px] p-3 bg-[#fb718508]">
          <div className="text-[12px] text-[var(--dim)] mb-2">
            {t("namespace_word")}: <b className="text-[var(--txt)]">{ns === ALL ? t("all_word") : ns}</b>
          </div>
          <div className="flex gap-2 mb-2.5 flex-wrap">
            {([...LAYERS, "stale"] as const).map((l) => (
              <button key={l} onClick={() => setClearLayer(clearLayer === l ? "" : l)}
                className={`px-2.5 py-1 rounded-[8px] border text-[11.5px] transition
                  ${clearLayer === l ? "border-[#fb7185] text-[#fb7185] bg-[#fb718518]"
                                     : "border-[var(--line)] text-[var(--dim)] hover:border-[#fb7185]/60"}`}>
                {l === "stale" ? t("stale_60d") : t(`layer_${l}` as any)}
              </button>
            ))}
            <button onClick={() => setClearLayer("")}
              className={`px-2.5 py-1 rounded-[8px] border text-[11.5px] transition
                ${!clearLayer ? "border-[#fb7185] text-[#fb7185] bg-[#fb718518]"
                              : "border-[var(--line)] text-[var(--dim)] hover:border-[#fb7185]/60"}`}>
              {t("clear_all_ns")}
            </button>
          </div>
          <input placeholder={`${t("confirm_clear")} (${CONFIRM_WORD})`}
            value={confirmText} onChange={e => setConfirmText(e.target.value)}
            className="w-full bg-[var(--panel2)] border border-[var(--line)] rounded-[8px] px-2.5 py-1.5 text-[12px] text-[var(--txt)] outline-none mb-2" />
          <button onClick={doClear} disabled={clearing || confirmText.trim().toUpperCase() !== CONFIRM_WORD}
            className="w-full flex items-center justify-center gap-2 py-2 rounded-[8px] border border-[#fb7185]/60
              text-[12.5px] text-[#fb7185] hover:bg-[#fb718520] disabled:opacity-30 disabled:cursor-not-allowed">
            <Trash2 size={13} /> {clearing ? t("clearing") : t("clear_layer")}
          </button>
          {clearMsg && <div className="text-[11.5px] text-[var(--dim)] mt-1.5 text-center">{clearMsg}</div>}
        </div>

        <button onClick={onClose}
          className="mt-5 w-full py-2.5 rounded-[10px] text-[13px] font-semibold text-white
            bg-gradient-to-br from-[var(--accent)] to-[var(--accent2)]">{t("done")}</button>
      </div>
    </div>
  );
}
