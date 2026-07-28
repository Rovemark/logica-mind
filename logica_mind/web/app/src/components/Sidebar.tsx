import { useState } from "react";
import { Settings as SettingsIcon, Sun, Moon } from "lucide-react";
import { getTheme, setTheme, effective } from "../theme";
import { VIEWS, CATS, type ViewKey } from "../nav";
import { ALL, type NsItem } from "../api";
import { useI18n } from "../i18n";
import { num } from "../fmt";

export default function Sidebar({
  view, ns, namespaces, colors, open, onView, onNs, onClose, onSettings, pronto = true,
}: {
  view: ViewKey; ns: string; namespaces: NsItem[]; colors: Record<string, string>;
  open: boolean; onView: (v: ViewKey) => void; onNs: (n: string) => void;
  onClose: () => void; onSettings: () => void; pronto?: boolean;
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
      <div className="px-[22px] pt-5 pb-4 flex items-center gap-3 border-b border-[var(--line)] flex-none">
        {/* O halo vivo do kit LogicaOS no lugar do ícone genérico de cérebro —
            mesma assinatura do dashboard e do Router. Gira de leve no hover. */}
        <span className="w-[34px] h-[34px] flex-none transition-transform duration-300 hover:rotate-[12deg]">
          <img src="/logicaos-halo-dark-64.png" alt="" className="lr-logo-dark w-full h-full" />
          <img src="/logicaos-halo-light-64.png" alt="" className="lr-logo-light w-full h-full" />
        </span>
        <div>
          <h1 className="text-[16px] m-0 font-bold tracking-tight">Logica&nbsp;Mind</h1>
          <small className="block text-[var(--dim2)] text-[10px] tracking-[.9px] uppercase mt-px">{t("brand_sub")}</small>
        </div>
      </div>

      {/* one scroll for the whole menu — categorized views, then namespaces */}
      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-3 flex flex-col gap-3">
        {CATS.map((c) => (
          <div key={c.key}>
            <div className="px-2 pb-1 text-[var(--dim2)] text-[10px] tracking-[.9px] uppercase font-medium">{t(c.tkey)}</div>
            <div className="flex flex-col gap-0.5">
              {VIEWS.filter((v) => v.cat === c.key).map(({ key, Icon }) => (
                <button key={key} onClick={() => onView(key)}
                  className={`flex items-center gap-[11px] px-3 py-[8px] rounded-[9px] font-medium text-[13.5px] text-left
                    ${view === key ? "bg-[var(--panel2)] text-[var(--txt)] shadow-[inset_0_0_0_1px_var(--line)]"
                                   : "text-[var(--dim)] hover:bg-[var(--panel2)] hover:text-[var(--txt)]"}`}>
                  <Icon size={16} strokeWidth={2} /> {t(key)}
                </button>
              ))}
            </div>
          </div>
        ))}

        <div>
          <div className="px-2 pb-1 text-[var(--dim2)] text-[10px] tracking-[.9px] uppercase font-medium">{t("agents_clones")}</div>
          <NsRow active={ns === ALL} dot="linear-gradient(90deg,#7c9cff,#a78bfa)" name={t("all_namespaces")} count={total} pronto={pronto} onClick={() => onNs(ALL)} />
          {namespaces.map((n) => (
            <NsRow key={n.namespace} active={ns === n.namespace} dot={colors[n.namespace] || "#7c9cff"}
              name={n.namespace} count={n.total} onClick={() => onNs(n.namespace)} />
          ))}
          {/* PERGUNTA: "não tenho nenhum agente?"
              Enquanto /namespaces não voltou, o menu afirmava "Nenhum dado ainda"
              — a mesma mentira do "0" no topo. Agora mostra 3 linhas-fantasma
              (a altura de uma linha real, 30px) e só diz "vazio" DEPOIS que a
              resposta chegou. */}
          {namespaces.length === 0 && (pronto
            ? <div className="text-[var(--dim)] text-center py-6 text-[12px]">{t("no_data_yet")}</div>
            : <div className="flex flex-col gap-1 px-[11px] py-2" aria-hidden>
                {[0, 1, 2].map((i) => <span key={i} className="lm-esqueleto h-[14px]" style={{ width: `${72 - i * 12}%` }} />)}
              </div>)}
        </div>
      </div>

      <div className="border-t border-[var(--line)] p-2.5 flex-none">
        <button onClick={onSettings}
          className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-[9px] text-[13px] font-medium
            ${view === "settings" ? "bg-[var(--panel2)] text-[var(--txt)] shadow-[inset_0_0_0_1px_var(--line)]"
                                  : "text-[var(--dim)] hover:bg-[var(--panel2)] hover:text-[var(--txt)]"}`}>
          <SettingsIcon size={16} /> {t("settings")}
        </button>
      </div>

      {/* Assinatura institucional — wordmark OFICIAL do kit, sem recolorir.
          Regra do kit: fundo claro → logo preta; escuro → branca. */}
      <div className="mt-auto flex items-center gap-2 border-t border-[var(--line)] px-3 py-2.5">
        {/* Alternador de tema VISÍVEL. Existia só dentro de Configurações — o dono não achava,
            e concluía que o painel não tinha modo claro. O mecanismo sempre funcionou
            (theme.ts + initTheme no boot); faltava a porta de entrada. */}
        <ThemeToggle />
        <div className="ml-auto flex items-center gap-1.5 opacity-55 transition-opacity duration-300 hover:opacity-90" title="Logica Mind — produto Rovemark">
          <span className="text-[9px] uppercase tracking-[0.14em] text-[var(--dim2)]">por</span>
          <img src="/rovemark-logo-white.svg" alt="Rovemark" className="lr-logo-dark h-[11px] w-auto" />
          <img src="/rovemark-logo-black.svg" alt="Rovemark" className="lr-logo-light h-[11px] w-auto" />
        </div>
      </div>
    </aside>
  );
}

function NsRow({ active, dot, name, count, onClick, pronto = true }:
  { active: boolean; dot: string; name: string; count: number; onClick: () => void; pronto?: boolean }) {
  return (
    // transition-colors 150ms: a linha se ANUNCIA antes do clique (responde
    // "isto é clicável?"). Só cor — mover o alvo debaixo do cursor faria ele fugir.
    <div onClick={onClick}
      className={`flex items-center gap-[9px] px-[11px] py-2 rounded-[9px] cursor-pointer border transition-colors duration-150
        ${active ? "bg-[var(--panel2)] text-[var(--txt)] border-[var(--line)]"
                 : "text-[var(--dim)] border-transparent hover:bg-[var(--panel2)] hover:text-[var(--txt)]"}`}>
      <span className="w-[9px] h-[9px] rounded-full flex-none" style={{ background: dot }} />
      <span className="flex-1 whitespace-nowrap overflow-hidden text-ellipsis font-medium">{name}</span>
      {/* Nunca "0" antes da resposta chegar: esqueleto no lugar do número. */}
      {pronto ? <span className="text-[var(--dim2)] text-xs tabular-nums">{num(count)}</span>
              : <span className="lm-esqueleto w-[38px] h-[10px]" aria-hidden />}
    </div>
  );
}


/** Alterna claro/escuro em um clique. Lê o tema EFETIVO (resolve o "auto") pra o ícone nunca
 *  mentir sobre o que está na tela. */
function ThemeToggle() {
  const [tema, setTema] = useState<"dark" | "light">(() => effective(getTheme()));
  const alternar = () => {
    const novo = tema === "dark" ? "light" : "dark";
    setTheme(novo);
    setTema(novo);
  };
  return (
    <button
      onClick={alternar}
      title={tema === "dark" ? "Mudar para o tema claro" : "Mudar para o tema escuro"}
      className="flex items-center gap-1.5 rounded-[8px] border border-[var(--line)] px-2 py-1
                 text-[11px] font-medium text-[var(--dim)] transition
                 hover:border-[var(--accent)] hover:text-[var(--txt)]"
    >
      {tema === "dark" ? <Sun size={13} /> : <Moon size={13} />}
      <span>{tema === "dark" ? "Claro" : "Escuro"}</span>
    </button>
  );
}
