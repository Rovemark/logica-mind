import { Sparkles } from "lucide-react";
import Markdown from "./Markdown";

// Renders the reflect() digest as a clean, de-duplicated list instead of a raw
// pre-wrapped blob (offline reflect returns "- fact\n- fact…").
export default function InsightList({ text }: { text: string }) {
  const lines = Array.from(
    new Set(
      (text || "")
        .split("\n")
        .map((l) => l.replace(/^[-•]\s*/, "").trim())
        .filter(Boolean),
    ),
  );
  if (!lines.length) return null;
  return (
    <div className="rounded-[13px] p-3 panel-grad">
      {lines.map((l, i) => (
        <div key={i} className="flex items-start gap-2.5 px-2 py-2 rounded-lg hover:bg-white/[0.03]">
          <Sparkles size={13} className="text-[var(--accent2)] mt-[3px] flex-none" />
          <Markdown text={l} className="text-[14px] leading-relaxed min-w-0" />
        </div>
      ))}
    </div>
  );
}
