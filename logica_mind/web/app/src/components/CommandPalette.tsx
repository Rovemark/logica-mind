import { useEffect, useMemo, useRef, useState } from "react";
import { Search, CornerDownLeft, Network, List as ListIcon, CircleUser, Boxes } from "lucide-react";
import { api, type NsItem, type Memory, type SearchEntity } from "../api";
import { VIEWS, type ViewKey } from "../nav";
import { useI18n } from "../i18n";

type Item =
  | { kind: "view"; key: ViewKey; label: string; Icon: any }
  | { kind: "agent"; ns: string; label: string }
  | { kind: "memory"; memory: Memory; label: string }
  | { kind: "entity"; entity: SearchEntity; label: string }
  | { kind: "category"; name: string; count: number; label: string };

// Global Spotlight (⌘K): one box over everything — views, agents, memories and
// graph entities — keyboard-navigable, each result jumps you straight there.
export default function CommandPalette({ namespaces, onClose, onView, onNs, onOpenMemory }: {
  namespaces: NsItem[];
  onClose: () => void;
  onView: (v: ViewKey) => void;
  onNs: (ns: string) => void;
  onOpenMemory: (m: Memory) => void;
}) {
  const { t } = useI18n();
  const [q, setQ] = useState("");
  const [mems, setMems] = useState<{ score: number; memory: Memory }[]>([]);
  const [ents, setEnts] = useState<SearchEntity[]>([]);
  const [cats, setCats] = useState<{ name: string; count: number }[]>([]);
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  // server search for memories + entities (debounced); views/agents filter locally
  useEffect(() => {
    const term = q.trim();
    if (!term) { setMems([]); setEnts([]); setCats([]); return; }
    const h = setTimeout(() => {
      api.search(term, 6).then((d) => { setMems(d.memories || []); setEnts(d.entities || []); setCats(d.categories || []); }).catch(() => {});
    }, 180);
    return () => clearTimeout(h);
  }, [q]);

  const ql = q.trim().toLowerCase();
  const viewItems: Item[] = VIEWS
    .filter((v) => !ql || t(v.key).toLowerCase().includes(ql) || v.key.includes(ql))
    .map((v) => ({ kind: "view", key: v.key, label: t(v.key), Icon: v.Icon }));
  const agentItems: Item[] = namespaces
    .filter((n) => !ql || n.namespace.toLowerCase().includes(ql))
    .slice(0, 8)
    .map((n) => ({ kind: "agent", ns: n.namespace, label: n.namespace }));
  const memItems: Item[] = mems.map((m) => ({ kind: "memory", memory: m.memory, label: m.memory.content }));
  const entItems: Item[] = ents.map((e) => ({ kind: "entity", entity: e, label: e.name }));
  const catItems: Item[] = cats.map((c) => ({ kind: "category", name: c.name, count: c.count, label: c.name }));

  const groups: { title: string; items: Item[] }[] = [
    { title: t("grp_views"), items: viewItems },
    { title: t("grp_agents"), items: agentItems },
    { title: t("grp_categories"), items: catItems },
    { title: t("grp_entities"), items: entItems },
    { title: t("grp_memories"), items: memItems },
  ].filter((g) => g.items.length);

  const flat = useMemo(() => groups.flatMap((g) => g.items), [q, mems, ents, cats, namespaces]);
  useEffect(() => { setSel(0); }, [q, mems, ents, cats]);

  function activate(it?: Item) {
    if (!it) return;
    if (it.kind === "view") onView(it.key);
    else if (it.kind === "agent") onNs(it.ns);
    else if (it.kind === "memory") onOpenMemory(it.memory);
    else if (it.kind === "entity") { onNs(it.entity.namespace); onView("graph"); }
    else if (it.kind === "category") onView("profile");
    onClose();
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, flat.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); activate(flat[sel]); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  }

  // keep the selected row in view
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-i="${sel}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  let idx = -1;
  return (
    <div className="fixed inset-0 z-[80] bg-black/45 backdrop-blur-[3px] grid place-items-start justify-center pt-[12vh] px-4" onClick={onClose}>
      <div className="w-full max-w-[620px] card-surface overflow-hidden shadow-[var(--shadow)] fadein" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2.5 px-4 py-3 border-b border-[var(--line)]">
          <Search size={17} className="text-[var(--dim2)] flex-none" />
          <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey}
            placeholder={t("spotlight_ph")}
            className="flex-1 bg-transparent outline-none border-0 text-[15px] text-[var(--txt)] placeholder:text-[var(--dim2)]" />
          <kbd className="text-[10px] text-[var(--dim2)] border border-[var(--line)] rounded px-1.5 py-0.5 flex-none">esc</kbd>
        </div>

        <div ref={listRef} className="max-h-[52vh] overflow-y-auto py-1.5">
          {flat.length === 0 ? (
            <div className="text-[var(--dim2)] text-center py-10 text-[13px]">{ql ? t("spotlight_empty") : t("spotlight_hint")}</div>
          ) : groups.map((g) => (
            <div key={g.title}>
              <div className="px-4 pt-2 pb-1 text-[10px] uppercase tracking-[.7px] text-[var(--dim2)]">{g.title}</div>
              {g.items.map((it) => {
                idx++;
                const i = idx;
                const active = i === sel;
                return (
                  <button key={itemKey(it)} data-i={i} onMouseEnter={() => setSel(i)} onClick={() => activate(it)}
                    className={`w-full flex items-center gap-2.5 px-4 py-2 text-left ${active ? "bg-[var(--panel2)]" : ""}`}>
                    <Glyph it={it} />
                    <span className="flex-1 min-w-0 truncate text-[13.5px] text-[var(--txt)]">{it.label}</span>
                    <Tag it={it} t={t} />
                    {active && <CornerDownLeft size={13} className="text-[var(--dim2)] flex-none" />}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// stable React key per item (index keys break selection across re-filtering)
function itemKey(it: Item): string {
  if (it.kind === "view") return "view-" + it.key;
  if (it.kind === "agent") return "agent-" + it.ns;
  if (it.kind === "entity") return "entity-" + it.entity.namespace + "-" + it.entity.name;
  if (it.kind === "category") return "cat-" + it.name;
  return "mem-" + it.memory.id;
}

function Glyph({ it }: { it: Item }) {
  if (it.kind === "view") { const I = it.Icon; return <I size={15} className="text-[var(--dim)] flex-none" />; }
  if (it.kind === "agent") return <CircleUser size={15} className="text-[var(--dim)] flex-none" />;
  if (it.kind === "entity") return <Network size={15} className="text-[var(--gold)] flex-none" />;
  if (it.kind === "category") return <Boxes size={15} className="text-[var(--accent2)] flex-none" />;
  return <ListIcon size={15} className="text-[var(--dim)] flex-none" />;
}

function Tag({ it, t }: { it: Item; t: (k: any) => string }) {
  const label = it.kind === "view" ? t("grp_views").slice(0, -1)
    : it.kind === "agent" ? "agent"
    : it.kind === "entity" ? (it.entity.type || "entity")
    : it.kind === "category" ? `${it.count}`
    : it.memory.layer;
  return <span className="text-[10px] text-[var(--dim2)] flex-none uppercase tracking-wide">{label}</span>;
}
