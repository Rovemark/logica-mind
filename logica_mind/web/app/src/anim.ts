import { useEffect, useRef, useState } from "react";

/** Devolve a classe de "piscada" por um instante toda vez que `v` MUDA de valor.
 *
 *  Pergunta que responde: "esse número mudou agora, ou eu que li errado?" — e,
 *  por tabela, "esta tela está viva ou congelou?". O painel refaz a busca sozinho
 *  a cada 8s; sem um sinal no dado que mudou, o dono olha um número parado e não
 *  sabe se é o mundo que está parado ou o software.
 *
 *  Não pisca na primeira renderização: APARECER não é MUDAR. Piscar tudo no boot
 *  seria decoração, e decoração aqui é ruído.
 *
 *  260ms de trava = os 240ms da animação + folga, pra a classe sair antes de uma
 *  eventual mudança seguinte poder reativá-la.
 */
export function useTick(v: unknown, cls = "lm-tick"): string {
  const primeira = useRef(true);
  const [ligado, setLigado] = useState(false);
  useEffect(() => {
    if (primeira.current) { primeira.current = false; return; }
    setLigado(true);
    const t = setTimeout(() => setLigado(false), 260);
    return () => clearTimeout(t);
  }, [v]);
  return ligado ? cls : "";
}
