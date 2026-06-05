import { Menu } from "lucide-react";
import { VIEWS, type ViewKey } from "../nav";
import { useI18n } from "../i18n";

// App-style bottom navigation — mobile only (hidden ≥820px). Five slots: the four
// primary views + a Menu button that opens the drawer (User, Insights, agents).
const PRIMARY: ViewKey[] = ["overview", "graph", "memories", "calendar"];

export default function TabBar({ view, onView, onMenu }: { view: ViewKey; onView: (v: ViewKey) => void; onMenu: () => void }) {
  const { t } = useI18n();
  const tabs = PRIMARY.map((k) => VIEWS.find((v) => v.key === k)!);
  const menuActive = !PRIMARY.includes(view);   // on a drawer-only view (User/Insights)
  return (
    <nav
      className="hidden max-[820px]:grid grid-flow-col auto-cols-fr fixed left-0 right-0 bottom-0 z-30
        glass border-t border-[var(--line)]"
      style={{ paddingBottom: "calc(7px + env(safe-area-inset-bottom))", paddingTop: 7 }}
    >
      {tabs.map(({ key, Icon }) => {
        const active = view === key;
        return (
          <button key={key} onClick={() => onView(key)}
            className={`flex flex-col items-center gap-[3px] py-[5px] px-0.5 rounded-[11px] text-[10px] font-semibold
              active:bg-[var(--panel2)] ${active ? "text-[var(--accent)]" : "text-[var(--dim2)]"}`}>
            <Icon size={19} strokeWidth={active ? 2.4 : 2} />
            {t(key)}
          </button>
        );
      })}
      <button onClick={onMenu}
        className={`flex flex-col items-center gap-[3px] py-[5px] px-0.5 rounded-[11px] text-[10px] font-semibold
          active:bg-[var(--panel2)] ${menuActive ? "text-[var(--accent)]" : "text-[var(--dim2)]"}`}>
        <Menu size={19} strokeWidth={menuActive ? 2.4 : 2} />
        {t("menu")}
      </button>
    </nav>
  );
}
