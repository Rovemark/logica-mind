import { useEffect, useState } from "react";
import { FolderGit2, FileCode, Boxes, Search } from "lucide-react";
import { api } from "../api";
import { useI18n } from "../i18n";

interface Dna { project: string; languages: { name: string; files: number }[]; frameworks: string[]; key_files: string[]; file_count: number; }

// Project DNA — point it at a folder (any repo) and the system reads its
// structure: languages, frameworks, key files. The coding-context brain made visible.
export default function Workspace() {
  const { t } = useI18n();
  const [path, setPath] = useState("");
  const [dna, setDna] = useState<Dna | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const scan = (p?: string) => {
    setLoading(true); setErr("");
    api.scan((p ?? path) || undefined).then((d) => { setDna(d); setLoading(false); })
      .catch((e) => { setErr(String(e)); setLoading(false); });
  };
  useEffect(() => { scan(); /* scan the server's cwd on open */ /* eslint-disable-next-line */ }, []);

  const maxFiles = dna ? Math.max(1, ...dna.languages.map((l) => l.files)) : 1;

  return (
    <div className="fadein">
      <h2 className="m-0 mb-1 text-[18px] font-bold tracking-tight">{t("workspace_dna_title")}</h2>
      <p className="text-[var(--dim)] text-[13px] mt-0 mb-4">{t("workspace_dna_desc")}</p>

      <div className="flex gap-2 mb-5 max-w-[620px]">
        <div className="flex-1 relative">
          <FolderGit2 size={15} className="absolute left-3 top-2.5 opacity-50" />
          <input value={path} onChange={(e) => setPath(e.target.value)} onKeyDown={(e) => e.key === "Enter" && scan()}
            placeholder={t("workspace_path_ph")}
            className="w-full bg-[var(--bg)] border border-[var(--line)] rounded-[10px] py-2.5 pl-9 pr-3 text-[13.5px] outline-none focus:border-[var(--accent)]" />
        </div>
        <button onClick={() => scan()}
          className="px-4 rounded-[10px] text-[13px] font-semibold text-white bg-gradient-to-br from-[var(--accent)] to-[var(--accent2)] inline-flex items-center gap-1.5">
          <Search size={15} /> {t("scan_word")}
        </button>
      </div>

      {err && <div className="text-[var(--warn)] text-[13px] mb-4">{err}</div>}
      {loading && <div className="text-[var(--dim)] py-8 text-center">{t("scanning_word")}</div>}

      {dna && !loading && (
        <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(260px,1fr))" }}>
          <div className="card-surface p-4">
            <div className="text-[var(--dim2)] text-[11px] uppercase tracking-[.7px] mb-3 flex items-center gap-2"><FileCode size={13} /> {t("ws_languages")} · {dna.file_count} {t("ws_files")}</div>
            {dna.languages.length ? dna.languages.map((l) => (
              <div key={l.name} className="mb-2.5">
                <div className="flex justify-between text-[13px] mb-1"><span>{l.name}</span><span className="text-[var(--dim2)] tabular-nums">{l.files}</span></div>
                <div className="h-1.5 rounded-full bg-[var(--panel2)] overflow-hidden">
                  <div className="h-full rounded-full bg-gradient-to-r from-[var(--accent)] to-[var(--accent2)]" style={{ width: `${(l.files / maxFiles) * 100}%` }} />
                </div>
              </div>
            )) : <div className="text-[var(--dim)] text-[13px]">{t("ws_no_code")}</div>}
          </div>

          <div className="card-surface p-4">
            <div className="text-[var(--dim2)] text-[11px] uppercase tracking-[.7px] mb-3 flex items-center gap-2"><Boxes size={13} /> {t("ws_frameworks")}</div>
            {dna.frameworks.length ? <div className="flex flex-wrap gap-1.5">{dna.frameworks.map((f) => <span key={f} className="text-[12.5px] bg-[var(--panel2)] border border-[var(--line)] px-2 py-1 rounded-lg">{f}</span>)}</div>
              : <div className="text-[var(--dim)] text-[13px]">{t("ws_none")}</div>}
            <div className="text-[var(--dim2)] text-[11px] uppercase tracking-[.7px] mt-4 mb-2">{t("ws_key_files")}</div>
            {dna.key_files.length ? dna.key_files.map((k) => <div key={k} className="text-[13px] font-mono text-[var(--dim)] py-0.5">{k}</div>)
              : <div className="text-[var(--dim)] text-[13px]">—</div>}
          </div>
        </div>
      )}
    </div>
  );
}
