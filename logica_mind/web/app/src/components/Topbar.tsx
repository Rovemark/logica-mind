import type { ReactNode } from "react";
import { Search } from "lucide-react";
import { ALL } from "../api";
import { useI18n } from "../i18n";
import { useTick } from "../anim";
import { num } from "../fmt";
import HelpTip from "./HelpTip";

// The header search is the global Spotlight trigger — clicking it (or ⌘K) opens
// the command palette that searches across everything. A contextual "?" explains
// whatever page you're on.
export default function Topbar({
  view, ns, total, onOpen, action, pronto = true,
}: { view: string; ns: string; total: number; onOpen: () => void; action?: ReactNode; pronto?: boolean }) {
  const { t } = useI18n();
  const mac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
  // A contagem se recarrega sozinha a cada 8s. Sem sinal no número, o dono não
  // sabe se a memória parou de crescer ou se o painel congelou. Só pisca quando
  // MUDA (240ms, uma vez) — ver anim.ts.
  const piscar = useTick(total);
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
        {/* "—" enquanto a contagem não chegou: o painel diz "ainda não sei" em vez
            de afirmar "zero". tabular-nums trava a largura pra o número não
            empurrar o resto da linha quando salta de 3 pra 5 dígitos. */}
        {/* num(): "85.267", não "85267" — o ponto de milhar entrega a ordem de
            grandeza sem o olho contar casa por casa. */}
        <b className={`text-[var(--txt)] tabular-nums ${piscar}`}>{pronto ? num(total) : "—"}</b> {t("memories_word")} · <b className="text-[var(--txt)]">{ns === ALL ? t("all_word") : ns}</b>
      </div>
      <HelpTip k={view} />
      {action && <div className="flex-none ml-1">{action}</div>}
    </div>
  );
}
