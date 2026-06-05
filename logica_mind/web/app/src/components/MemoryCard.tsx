import { Trash2, Plug } from "lucide-react";
import type { Memory } from "../api";
import { tShort } from "../api";
import { useOpenMemory } from "../memctx";
import { useI18n } from "../i18n";

// colour a fact's category chip by the group of its life/work dimension
export function dimColor(dim?: string | null): string {
  if (!dim) return "var(--accent2)";
  if (dim.startsWith("biz_")) return "#4ade80";
  if (dim.startsWith("project_")) return "#7c9cff";
  if (dim.startsWith("org_")) return "#22d3ee";
  return "#a78bfa";
}

export function LayerPill({ layer }: { layer: string }) {
  const { t } = useI18n();
  const label = t(`layer_${layer}` as any) || layer.toUpperCase();
  return (
    <span className={`bg-${layer} text-[10px] px-2 py-[2px] rounded-full font-bold uppercase tracking-wide`}>
      {label}
    </span>
  );
}

// known MCP clients / hosts → pretty labels (matched case-insensitively, and on a
// substring so "cursor-vscode"/"claude-ai" still resolve). Unknown clients fall
// back to a prettified version of whatever name they self-reported.
const SRC_LABEL: [string, string][] = [
  ["claude-code", "Claude Code"], ["claude", "Claude"], ["cursor", "Cursor"],
  ["antigravity", "Antigravity"], ["windsurf", "Windsurf"], ["codeium", "Windsurf"],
  ["chatgpt", "ChatGPT"], ["openai", "ChatGPT"], ["cline", "Cline"], ["continue", "Continue"],
  ["zed", "Zed"], ["gemini", "Gemini"], ["copilot", "Copilot"], ["visual studio code", "VS Code"],
  ["vscode", "VS Code"], ["logica", "Logica Mind"], ["mcp", "via MCP"],
];

function sourceLabel(source: string): string {
  const s = source.toLowerCase();
  for (const [k, v] of SRC_LABEL) if (s.includes(k)) return v;
  return source.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());  // prettify unknown
}

// Where a memory was captured from (the MCP client / hook host) — makes it
// obvious that the Logica Mind MCP picked this up.
export function SourceBadge({ source }: { source?: string | null }) {
  const { t } = useI18n();
  if (!source) return null;
  const label = sourceLabel(source);
  return (
    <span className="inline-flex items-center gap-1 text-[10px] text-[var(--accent2)] bg-[var(--panel2)]
      border border-[var(--line)] px-1.5 py-[1px] rounded-full" title={`${t("captured_via")} ${label} (${source})`}>
      <Plug size={9} /> {label}
    </span>
  );
}

export default function MemoryCard({
  m, score, components, onClick, highlight, onDelete,
}: { m: Memory; score?: number; components?: Record<string, any>; onClick?: () => void; highlight?: boolean; onDelete?: () => void }) {
  const { t } = useI18n();
  const comp = components
    ? Object.entries(components).map(([k, v]) => `${k} ${v}`).join(" · ")
    : "";
  const openMem = useOpenMemory();
  const handleClick = onClick || (() => openMem(m));   // default: open as an Obsidian-style note
  return (
    <div id={`mc-${m.id}`} onClick={handleClick}
      className={`group relative card-surface px-4 py-3 mb-[11px] fadein transition
        cursor-pointer hover:border-[var(--accent)]/60 hover:bg-[var(--panel2)]
        ${highlight ? "ring-2 ring-[var(--accent)] border-[var(--accent)]" : ""}`}>
      {onDelete && (
        <button onClick={(e) => { e.stopPropagation(); onDelete(); }} title={t("delete_word")}
          className="absolute top-2.5 right-2.5 text-[var(--dim2)] hover:text-[var(--warn)] opacity-0 group-hover:opacity-100 transition">
          <Trash2 size={14} />
        </button>
      )}
      <div className="flex items-center gap-[9px] mb-1.5 pr-5 flex-wrap">
        <LayerPill layer={m.layer} />
        {m.metadata?.category && (() => { const dc = dimColor(m.metadata?.dimension); return (
          <span className="text-[10.5px] font-semibold px-2 py-[1px] rounded-full" style={{ background: `${dc}1f`, color: dc }}>
            {m.metadata.category}
          </span>
        ); })()}
        <span className="text-[11px] text-[var(--dim)] bg-[var(--panel2)] border border-[var(--line)] px-2 py-[1px] rounded-full">
          {m.namespace}
        </span>
        <SourceBadge source={m.metadata?.source} />
        {score != null && (
          <span className="ml-auto tabular-nums text-[var(--good)] font-bold">{score}</span>
        )}
      </div>
      <div className="text-[14.5px] leading-relaxed">{m.content}</div>
      <div className="text-[var(--dim2)] text-xs mt-1.5 flex gap-3 flex-wrap">
        <span>{tShort(m.created_at)}</span>
        {comp && <span>{comp}</span>}
        {m.tags && m.tags.length > 0 && <span>#{m.tags.join(" #")}</span>}
        {!!m.access_count && <span>{t("recalled_word")} {m.access_count}×</span>}
      </div>
    </div>
  );
}
