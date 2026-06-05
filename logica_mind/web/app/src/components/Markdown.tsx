import type { ReactNode } from "react";

// Lightweight Markdown for memory content — bold/italic/code inline, plus
// headings, bullet lists and paragraphs. No HTML injection (parsed to elements).
function inline(text: string, kb: string): ReactNode[] {
  const out: ReactNode[] = [];
  // order matters: ** / __ (bold) before * / _ (italic)
  const re = /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*\s][^*]*\*|_[^_\s][^_]*_|\[[^\]]+\]\([^)]+\))/g;
  let last = 0, m: RegExpExecArray | null, k = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**") || tok.startsWith("__")) out.push(<strong key={kb + k++}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) out.push(<code key={kb + k++} className="px-1 py-0.5 rounded bg-[var(--panel2)] border border-[var(--line)] text-[.88em]">{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("[")) { const mm = tok.match(/^\[([^\]]+)\]\(([^)]+)\)$/)!; out.push(<a key={kb + k++} href={mm[2]} target="_blank" rel="noreferrer" className="text-[var(--accent)] underline">{mm[1]}</a>); }
    else out.push(<em key={kb + k++}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export default function Markdown({ text, className = "" }: { text: string; className?: string }) {
  const lines = (text || "").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0, key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const h = line.match(/^(#{1,3})\s+(.*)$/);
    if (h) { const lvl = h[1].length; blocks.push(<div key={key++} className={`font-bold mt-1.5 ${lvl === 1 ? "text-[1.12em]" : "text-[1.04em]"}`}>{inline(h[2], `h${key}`)}</div>); i++; continue; }
    if (/^[-*•]\s+/.test(line)) {
      const items: ReactNode[] = [];
      while (i < lines.length && /^[-*•]\s+/.test(lines[i])) { items.push(<li key={key++} className="ml-1">{inline(lines[i].replace(/^[-*•]\s+/, ""), `li${key}`)}</li>); i++; }
      blocks.push(<ul key={key++} className="my-1 ml-4 list-disc space-y-0.5">{items}</ul>); continue;
    }
    blocks.push(<p key={key++} className="m-0 mt-1 first:mt-0">{inline(line, `p${key}`)}</p>); i++;
  }
  return <div className={className}>{blocks}</div>;
}
