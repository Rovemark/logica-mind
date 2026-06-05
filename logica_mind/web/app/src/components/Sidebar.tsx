import { Brain, Settings as SettingsIcon } from "lucide-react";
import { VIEWS, type ViewKey } from "../nav";
import { ALL, type NsItem } from "../api";
import { useI18n } from "../i18n";

export default function Sidebar({
  view, ns, namespaces, colors, open, onView, onNs, onClose, onSettings,
}: {
  view: ViewKey; ns: string; namespaces: NsItem[]; colors: Record<string, string>;
  open: boolean; onView: (v: ViewKey) => void; onNs: (n: string) => void;
  onClose: () => void; onSettings: () => void;
}) {
  const { t } = useI18n();
  const total = namespaces.reduce((a, n) => a + n.total, 0);
  return (
    <aside
      className={`flex flex-col min-h-0 border-r border-[var(--line)] bg-gradient-to-b from-[var(--bg2)] to-[var(--bg)]
        max-[820px]:fixed max-[820px]:left-0 max-[820px]:top-0 max-[820px]:bottom-0 max-[820px]:w-[264px] max-[820px]:max-w-[86vw]
        max-[820px]:z-50 max-[820px]:shadow-[var(--shadow)] max-[820px]:transition-transform max-[820px]:duration-200
        ${open ? "max-[820px]:translate-x-0" : "max-[820px]:-translate-x-full"}`}
    >
      <div className="px-[22px] pt-5 pb-4 flex items-center gap-3 border-b border-[var(--line)]">
        <div className="w-[30px] h-[30px] rounded-[9px] grid place-items-center text-white
          bg-gradient-to-br from-[var(--accent)] to-[var(--accent2)] shadow-[0_4px_14px_rgba(124,156,255,.4)]">
          <Brain size={17} />
        </div>
        <div>
          <h1 className="text-[16px] m-0 font-bold tracking-tight">Logica&nbsp;Mind</h1>
          <small className="block text-[var(--dim2)] text-[10px] tracking-[.9px] uppercase mt-px">{t("brand_sub")}</small>
        </div>
      </div>

      <nav className="px-3 pt-3 pb-1 flex flex-col gap-0.5">
        {VIEWS.map(({ key, Icon }) => (
          <button key={key} onClick={() => onView(key)}
            className={`flex items-center gap-[11px] px-3 py-[9px] rounded-[9px] font-medium text-[13.5px] text-left
              ${view === key ? "bg-[var(--panel2)] text-[var(--txt)] shadow-[inset_0_0_0_1px_var(--line)]"
                             : "text-[var(--dim)] hover:bg-[var(--panel2)] hover:text-[var(--txt)]"}`}>
            <Icon size={16} strokeWidth={2} /> {t(key)}
          </button>
        ))}
      </nav>

      <div className="px-[22px] pt-3.5 pb-1.5 text-[var(--dim2)] text-[10px] tracking-[.9px] uppercase">{t("agents_clones")}</div>
      <div className="overflow-y-auto flex-1 px-2.5 pb-3">
        <NsRow active={ns === ALL} dot="linear-gradient(90deg,#7c9cff,#a78bfa)" name={t("all_namespaces")} count={total} onClick={() => onNs(ALL)} />
        {namespaces.map((n) => (
          <NsRow key={n.namespace} active={ns === n.namespace} dot={colors[n.namespace] || "#7c9cff"}
            name={n.namespace} count={n.total} onClick={() => onNs(n.namespace)} />
        ))}
        {namespaces.length === 0 && <div className="text-[var(--dim)] text-center py-6">{t("no_data_yet")}</div>}
      </div>

      {/* the graph legend lives inside the Graph view (collapsible), so the sidebar
          stays clean and the namespace list gets the full height — it scrolls when
          there are many agents instead of fighting a fixed legend block. */}
      <div className="border-t border-[var(--line)] p-2.5">
        <button onClick={onSettings}
          className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-[9px] text-[13px] font-medium
            text-[var(--dim)] hover:bg-[var(--panel2)] hover:text-[var(--txt)]">
          <SettingsIcon size={16} /> {t("settings")}
        </button>
      </div>
    </aside>
  );
}

function NsRow({ active, dot, name, count, onClick }:
  { active: boolean; dot: string; name: string; count: number; onClick: () => void }) {
  return (
    <div onClick={onClick}
      className={`flex items-center gap-[9px] px-[11px] py-2 rounded-[9px] cursor-pointer border
        ${active ? "bg-[var(--panel2)] text-[var(--txt)] border-[var(--line)]"
                 : "text-[var(--dim)] border-transparent hover:bg-[var(--panel2)] hover:text-[var(--txt)]"}`}>
      <span className="w-[9px] h-[9px] rounded-full flex-none" style={{ background: dot }} />
      <span className="flex-1 whitespace-nowrap overflow-hidden text-ellipsis font-medium">{name}</span>
      <span className="text-[var(--dim2)] text-xs tabular-nums">{count}</span>
    </div>
  );
}
