// O carregamento OFICIAL do LogicaOS — o halo VIVO do kit.
// Usa o logicaos-halo-animated.webp, que TOCA SOZINHO num <img> (é o que o
// halo-loader.html do próprio kit faz) — nada de sprite nem keyframes. Como o
// arquivo tem 8,5MB, o PNG estático fica POR BAIXO desde o primeiro paint
// (respirando) e o animado entra por cima quando terminar de baixar; depois do
// primeiro load o browser cacheia e é instantâneo. prefers-reduced-motion fica
// no estático.
import { useState } from "react";
import { useI18n } from "../i18n";

export default function HaloLoading({ size = 84, label, className = "" }: {
  size?: number; label?: string; className?: string;
}) {
  const { t } = useI18n();
  const [vivo, setVivo] = useState(false);

  return (
    <div className={`flex flex-col items-center justify-center gap-3 ${className}`}>
      <span className="relative block" style={{ width: size, height: size }}>
        {!vivo && <>
          <img src="/logicaos-halo-dark-256.png" alt="" className="lr-logo-dark absolute inset-0 w-full h-full lm-halo-breathe" />
          <img src="/logicaos-halo-light-256.png" alt="" className="lr-logo-light absolute inset-0 w-full h-full lm-halo-breathe" />
        </>}
        <img src="/logicaos-halo-animated.webp" alt="" onLoad={() => setVivo(true)}
          className={`absolute inset-0 w-full h-full motion-reduce:hidden ${vivo ? "" : "opacity-0"}`} />
      </span>
      <span className="text-[var(--dim)] text-[13px]">{label ?? t("loading")}</span>
    </div>
  );
}
