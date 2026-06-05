import type { ReactNode } from "react";
import { Search } from "lucide-react";
import { ALL } from "../api";
import { useI18n } from "../i18n";
import HelpTip from "./HelpTip";

// The header search is the global Spotlight trigger — clicking it (or ⌘K) opens
// the command palette that searches across everything. A contextual "?" explains
// whatever page you're on.
export default function Topbar({
  view, ns, total, onOpen, action,
}: { view: string; ns: string; total: number; onOpen: () => void; action?: ReactNode }) {
  const { t } = useI18n();
  const mac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
  return (
    <div className="flex items-center gap-3.5 px-6 py-3.5 border-b border-[var(--line)] bg-[var(--bg2)] max-[820px]:px-3.5">
      <button onClick={onOpen}
        className="flex-1 relative max-w-[620px] flex items-center gap-2.5 bg-[var(--bg)] border border-[var(--line)]
          rounded-[11px] py-[11px] pl-10 pr-3 text-left hover:border-[var(--accent)]/60 group">
        <Search size={16} className="absolute left-3.5 opacity-50" />
        <span className="flex-1 text-[14.5px] text-[var(--dim2)] truncate">{t("spotlight_open")}</span>
        <kbd className="text-[10.5px] text-[var(--dim2)] border border-[var(--line)] rounded px-1.5 py-0.5 flex-none max-[820px]:hidden">
          {mac ? "⌘" : "Ctrl"} K
        </kbd>
      </button>
      <div className="ml-auto text-[var(--dim)] text-[12.5px] flex items-center gap-2 max-[820px]:hidden">
        <b className="text-[var(--txt)]">{total}</b> {t("memories_word")} · <b className="text-[var(--txt)]">{ns === ALL ? t("all_word") : ns}</b>
      </div>
      <HelpTip k={view} />
      {action && <div className="flex-none ml-1">{action}</div>}
    </div>
  );
}
