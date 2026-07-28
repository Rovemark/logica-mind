// Estado vazio.
//
// Pergunta que responde: "está vazio de verdade, ou quebrou?"
// Uma frase cinza solta no meio do branco lê como erro. Um bloco desenhado —
// símbolo do LogicaOS apagado + a frase — lê como resposta do sistema.
//
// SEM movimento de propósito: o vazio não tem nada de novo pra anunciar, e
// animação sem informação é ruído. O símbolo fica a 22% (é textura, não
// conteúdo); o texto mantém var(--dim), que é a cor de leitura já usada no
// painel — nada de cinza sobre cinza.
export default function Empty({ text, className = "" }: { text: string; className?: string }) {
  return (
    <div className={`flex flex-col items-center justify-center gap-3 py-12 text-center ${className}`}>
      <span className="w-11 h-11 opacity-[0.22] flex-none">
        <img src="/logicaos-halo-dark-64.png" alt="" className="lr-logo-dark w-full h-full" />
        <img src="/logicaos-halo-light-64.png" alt="" className="lr-logo-light w-full h-full" />
      </span>
      <span className="text-[13px] text-[var(--dim)]">{text}</span>
    </div>
  );
}
