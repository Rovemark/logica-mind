// O carregamento OFICIAL do LogicaOS — o halo vivo do kit, respirando.
// Um componente só pra TODOS os estados de "carregando" do app: onde antes cada
// tela escrevia seu próprio texto seco, agora a marca ocupa a espera.
// `size` calibra ao contexto: 120 pra palcos grandes (grafo), 64 pra listas,
// 40 pra detalhes inline.
import { useI18n } from "../i18n";

export default function HaloLoading({ size = 84, label, className = "" }: {
  size?: number; label?: string; className?: string;
}) {
  const { t } = useI18n();
  return (
    <div className={`flex flex-col items-center justify-center gap-3 ${className}`}>
      <span className="relative" style={{ width: size, height: size }}>
        <img src="/logicaos-halo-dark-256.png" alt="" className="lr-logo-dark absolute inset-0 w-full h-full lm-halo-breathe" />
        <img src="/logicaos-halo-light-256.png" alt="" className="lr-logo-light absolute inset-0 w-full h-full lm-halo-breathe" />
      </span>
      <span className="text-[var(--dim)] text-[13px]">{label ?? t("loading")}</span>
    </div>
  );
}
