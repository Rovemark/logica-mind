import type { ReactNode } from "react";
import { Search } from "lucide-react";
import { ALL } from "../api";
import { useI18n } from "../i18n";

export default function Topbar({
  q, ns, total, onSearch, action,
}: { q: string; ns: string; total: number; onSearch: (v: string) => void; action?: ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-3.5 px-6 py-3.5 border-b border-[var(--line)] bg-[var(--bg2)] max-[820px]:px-3.5">
      <div className="flex-1 relative max-w-[620px]">
        <Search size={16} className="absolute left-3.5 top-3 opacity-50" />
        <input
          value={q}
          onChange={(e) => onSearch(e.target.value)}
          placeholder={t("search_ph")}
          className="w-full bg-[var(--bg)] border border-[var(--line)] text-[var(--txt)] rounded-[11px]
            py-[11px] pl-10 pr-3.5 text-[14.5px] outline-none focus:border-[var(--accent)]
            focus:shadow-[0_0_0_3px_rgba(124,156,255,.12)] max-[820px]:text-[16px]"
        />
      </div>
      <div className="ml-auto text-[var(--dim)] text-[12.5px] flex items-center gap-2 max-[820px]:hidden">
        <b className="text-[var(--txt)]">{total}</b> {t("memories_word")} · <b className="text-[var(--txt)]">{ns === ALL ? t("all_word") : ns}</b>
      </div>
      {action && <div className="flex-none ml-1">{action}</div>}
    </div>
  );
}
