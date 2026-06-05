import { useEffect, useState } from "react";
import { MessagesSquare, Pencil, Check, X, Download, Users, Activity, Link2, CheckCircle2 } from "lucide-react";
import { api, tShort, type SessionItem, type Memory, type SessionRecordMeta } from "../api";
import MemoryCard, { SourceBadge } from "../components/MemoryCard";
import Pager, { paginate } from "../components/Pager";
import { useI18n } from "../i18n";

// Rich header for a structured session/run record (generic: participants + roles
// + metrics + links — no framework-specific terms).
function SessionRecordHeader({ rec }: { rec: SessionRecordMeta }) {
  const { t } = useI18n();
  const parts = rec.participants || [];
  const metrics = Object.entries(rec.metrics || {});
  const links = Object.entries(rec.links || {});
  return (
    <div className="card-surface p-4 mb-3.5">
      <div className="flex items-center gap-2 mb-2.5">
        {rec.status === "completed"
          ? <CheckCircle2 size={14} className="text-[var(--accent)] flex-none" />
          : <Activity size={14} className="text-[var(--gold)] flex-none" />}
        <span className="text-[14px] font-semibold flex-1 leading-snug">{rec.title}</span>
        {rec.status && (
          <span className="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full border
            border-[var(--line)] text-[var(--dim)] bg-[var(--panel2)]">{rec.status}</span>
        )}
      </div>

      {metrics.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-[var(--dim)] mb-3">
          {metrics.map(([k, v]) => (
            <span key={k}><span className="text-[var(--dim2)]">{k}</span> <b className="text-[var(--txt)] tabular-nums">{String(v)}</b></span>
          ))}
        </div>
      )}

      {parts.length > 0 && (
        <>
          <div className="text-[var(--dim2)] text-[10px] uppercase tracking-[.7px] mb-1.5 flex items-center gap-1.5">
            <Users size={11} /> {t("participants")} · {parts.length}
          </div>
          <div className="flex flex-wrap gap-1.5 mb-1">
            {parts.map((p, i) => (
              <span key={i} className="inline-flex items-center gap-1.5 text-[11.5px] bg-[var(--panel2)]
                border border-[var(--line)] rounded-full px-2 py-0.5">
                <span className="font-medium text-[var(--txt)]">{p.name}</span>
                {p.role && <span className="text-[var(--accent2)]">{p.role}</span>}
                {p.metrics && Object.entries(p.metrics).map(([k, v]) =>
                  <span key={k} className="text-[var(--dim2)] tabular-nums">{k} {String(v)}</span>)}
              </span>
            ))}
          </div>
        </>
      )}

      {links.length > 0 && (
        <div className="flex flex-wrap gap-3 text-[11px] text-[var(--dim2)] mt-2">
          {links.map(([k, v]) => (
            <span key={k} className="inline-flex items-center gap-1"><Link2 size={10} /> {k}: <span className="text-[var(--dim)]">{v}</span></span>
          ))}
        </div>
      )}
    </div>
  );
}

function RenameInline({ session, onDone }: { session: SessionItem; onDone: (name: string) => void }) {
  const { t } = useI18n();
  const [val, setVal] = useState(session.name || session.id);
  const [saving, setSaving] = useState(false);

  async function save() {
    if (!val.trim()) return;
    setSaving(true);
    await api.renameSession(session.id, val.trim()).catch(() => {});
    setSaving(false);
    onDone(val.trim());
  }

  return (
    <div className="flex items-center gap-1.5 mt-1">
      <input
        className="flex-1 bg-[var(--panel2)] border border-[var(--accent)]/60 rounded-[7px] px-2 py-1 text-[12px] text-[var(--txt)] outline-none"
        value={val} onChange={e => setVal(e.target.value)}
        onKeyDown={e => { if (e.key === "Enter") save(); if (e.key === "Escape") onDone(""); }}
        autoFocus
      />
      <button onClick={save} disabled={saving}
        className="text-[var(--accent)] hover:text-[var(--txt)] disabled:opacity-40"><Check size={13} /></button>
      <button onClick={() => onDone("")} className="text-[var(--dim)] hover:text-[var(--txt)]"><X size={13} /></button>
    </div>
  );
}

export default function Sessions({ ns }: { ns: string }) {
  const { t } = useI18n();
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [sel, setSel] = useState<SessionItem | null>(null);
  const [mems, setMems] = useState<Memory[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [page, setPage] = useState(1);

  const load = () =>
    api.sessions(ns).then((d) => {
      const list = d.sessions || [];
      setSessions(list);
      setSel(prev => prev ? (list.find(s => s.id === prev.id && s.namespace === prev.namespace) || list[0] || null) : list[0] || null);
    }).catch(() => setSessions([]));

  useEffect(() => { load(); setPage(1); }, [ns]);
  const spg = paginate(sessions, page, 12);

  useEffect(() => {
    if (!sel) { setMems([]); return; }
    api.sessionMemories(sel.namespace, sel.id).then((d) => setMems(d.memories)).catch(() => setMems([]));
  }, [sel]);

  async function importClaude() {
    setImporting(true);
    const res = await api.claudeImport().catch(() => ({ imported: 0 }));
    setImporting(false);
    if (res.imported > 0) load();
    else alert(t("no_claude_sessions"));
  }

  function handleRenameDone(sid: string, newName: string) {
    setEditing(null);
    if (newName) {
      setSessions(ss => ss.map(s => s.id === sid ? { ...s, name: newName } : s));
      if (sel?.id === sid) setSel(s => s ? { ...s, name: newName } : s);
    }
  }

  function exportSession() {
    if (!sel || !mems.length) return;
    const blob = new Blob([JSON.stringify({ session: sel, memories: mems }, null, 2)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `session-${sel.id.slice(0, 8)}.json`; a.click(); URL.revokeObjectURL(a.href);
  }

  return (
    <div className="fadein flex gap-4 max-[900px]:flex-col">
      {/* session list */}
      <div className="w-[330px] max-w-full flex-none">
        <div className="flex items-center mb-4 gap-2">
          <h2 className="m-0 text-[18px] font-bold tracking-tight flex-1">{t("sessions")}</h2>
          <button onClick={importClaude} disabled={importing} title={t("import_claude")}
            className="text-[11px] px-2 py-1 rounded-[7px] border border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)] hover:border-[var(--accent)]/50 disabled:opacity-40">
            {importing ? t("importing") : "↓ Claude"}
          </button>
        </div>
        {sessions.length ? (<>{spg.slice.map((s, i) => {
          const on = sel && sel.id === s.id && sel.namespace === s.namespace;
          const isEditing = editing === s.id;
          return (
            <div key={i} onClick={() => { setSel(s); setEditing(null); }}
              className={`w-full text-left card-surface px-3.5 py-3 mb-2 transition cursor-pointer
                ${on ? "border-[var(--accent)] ring-1 ring-[var(--accent)]/40" : "hover:border-[var(--accent)]/50"}`}>
              <div className="flex items-center gap-2">
                <MessagesSquare size={13} className="text-[var(--accent2)] flex-none" />
                <span className="font-semibold text-[var(--txt)] text-[13px] truncate flex-1">
                  {s.name || s.id.slice(0, 16)}
                </span>
                <span className="text-[var(--dim2)] text-[11px] tabular-nums flex-none">{s.count}</span>
                {on && !isEditing && (
                  <button onClick={(e) => { e.stopPropagation(); setEditing(s.id); }}
                    className="text-[var(--dim)] hover:text-[var(--txt)] flex-none ml-0.5">
                    <Pencil size={11} />
                  </button>
                )}
              </div>
              {isEditing && (
                <div onClick={e => e.stopPropagation()}>
                  <RenameInline session={s} onDone={(name) => handleRenameDone(s.id, name)} />
                </div>
              )}
              {!isEditing && (
                <div className="text-[var(--dim2)] text-[11.5px] mt-1 flex gap-2 items-center flex-wrap">
                  <span>{tShort(s.last)?.slice(0, 10)}</span>
                  <span className="bg-[var(--panel2)] border border-[var(--line)] px-1.5 rounded">{s.namespace}</span>
                  <SourceBadge source={s.source} />
                </div>
              )}
            </div>
          );
        })}<Pager page={spg.page} pages={spg.pages} onPage={setPage} /></>) : <div className="text-[var(--dim)] card-surface text-center py-10">{t("no_sessions")}</div>}
      </div>

      {/* session detail */}
      <div className="flex-1 min-w-0">
        <div className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px] mb-2.5 h-[26px] flex items-center gap-3">
          {sel ? (
            <>
              <span className="truncate">{sel.name || sel.id.slice(0, 20)} · {mems.length}</span>
              {mems.length > 0 && (
                <button onClick={exportSession} title={t("export_session")} className="ml-auto text-[var(--dim)] hover:text-[var(--txt)]">
                  <Download size={13} />
                </button>
              )}
            </>
          ) : t("pick_session")}
        </div>
        {sel ? (
          <>
            {sel.record && <SessionRecordHeader rec={sel.record} />}
            {/* hide the record's own body card (it's shown richly in the header) */}
            {(() => {
              const cards = mems.filter((m) => !sel.record || !(m.metadata?.record));
              return cards.length ? cards.map((m) => <MemoryCard key={m.id} m={m} />)
                : (!sel.record && <div className="text-[var(--dim)] card-surface text-center py-10">{t("nothing_here")}</div>);
            })()}
          </>
        ) : (
          <div className="text-[var(--dim)] card-surface text-center py-10">{t("pick_session")}</div>
        )}
      </div>
    </div>
  );
}
