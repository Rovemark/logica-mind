import { Sparkles, Info } from "lucide-react";
import Markdown from "./Markdown";

/**
 * INSIGHT — e a diferença entre um insight e um despejo.
 *
 * O `reflect()` do servidor SINTETIZA com LLM quando há um configurado. Sem LLM,
 * ele devolve o "digest" — as memórias recentes cruas — e isso é o comportamento
 * documentado dele, não um defeito.
 *
 * O defeito estava aqui: a tela rotulava esse digest como INSIGHT e o exibia como
 * se fosse conclusão do sistema. Na prática, a PRIMEIRA tela do painel de memória
 * mostrava turnos de conversa inteiros, com `\n` literais, `[object Object]` e o
 * andaime interno dos prompts ("## Formato de Resposta", "Estruture seu output
 * com:"). Quem abre o painel lê aquilo como se a IA tivesse concluído aquilo — e
 * não concluiu: ela nem foi chamada.
 *
 * Duas correções, ambas de apresentação (o dado não muda):
 *
 * 1. LIMPEZA — escapes literais viram quebra de verdade, o andaime de prompt é
 *    cortado e `[object Object]` (rastro de uma serialização que falhou lá atrás)
 *    some. Lixo de serialização não informa nada a ninguém.
 *
 * 2. HONESTIDADE — quando o conteúdo é o digest cru, o rótulo diz isso. Chamar de
 *    "insight" uma lista de lembranças recentes é a mesma classe de erro que
 *    mostrar zero enquanto carrega: uma afirmação que o sistema não sustenta.
 */

/**
 * Sinais de que a linha é ANDAIME DE PROMPT, não conteúdo.
 *
 * A lista abaixo não foi imaginada: cada padrão veio de uma linha que apareceu
 * de fato na tela. O `reflect()` sem LLM devolve turnos inteiros de conversa, e
 * um turno carrega o arcabouço que o sistema montou para o agente — cabeçalhos
 * de seção, rótulos de formato, faixas de separação, o caminho do diretório.
 * Nada disso é uma lembrança sobre o Arquiteto; é a estrutura em volta dela.
 */
const ANDAIME = new RegExp([
  '^#{1,3}\\s*(sua tarefa|formato de resposta|contexto|pedido)',
  '^[═=─-]{3,}',                                   // faixas de separação
  '^"?[═=]{2,}\\s*(contexto|pedido)',              // "═══ CONTEXTO DA SESSÃO"
  '^(análise|decisão|ações|resposta|output):\\s*$', // rótulo de formato sozinho
  '^(análise|decisão|ações):\\s*(sua avaliação|a decisão|próximos passos)', // o gabarito
  '^estruture seu output',
  '^responda apenas:',                             // instrução de teste
  '^(analise e monte|execute isto|verbatim)',
  '^(diretório de trabalho|projeto em foco):',
  // carimbo de autoria sem NADA depois — o turno foi gravado vazio. A linha
  // ocupa espaço e não informa quem disse o quê, porque não foi dito nada.
  '^(o arquiteto disse|conclus[ãa]o do assistente)[^:]*:\\s*$',
  '^\\{|^\\}|^\\[|^\\]',                           // JSON solto
].join('|'), 'i');

function limpar(bruto: string): string[] {
  return Array.from(new Set(
    (bruto || "")
      // escapes que chegaram como TEXTO — algo no caminho serializou duas vezes,
      // e o usuário via "\n" literal no meio da frase
      .replace(/\\n/g, "\n")
      .replace(/\\"/g, '"')
      // rastro de serialização falha: ocupa a linha e não diz nada
      .replace(/\[object Object\]/g, "")
      .split("\n")
      .map((l) => l.replace(/^[-•]\s*/, "").trim())
      // O teste do andaime roda sobre a linha SEM ênfase markdown: o gabarito
      // chega como "**Análise:** sua avaliação do cenário", e um regex ancorado
      // em "^análise" nunca casaria com o asterisco na frente. Tira-se a marcação
      // só para DECIDIR; o texto exibido continua o original, com o negrito.
      .filter((l) => {
        const nu = l.replace(/[*_`]/g, "").trim();
        return nu && !ANDAIME.test(nu) && nu.length > 2;
      }),
  ));
}

/**
 * É síntese de verdade ou o digest cru?
 *
 * A primeira versão contava linhas começadas em "- " — e errava, porque o
 * digest chega com um "- " por MEMÓRIA, e cada memória tem várias linhas
 * internas. O denominador ficava grande e a proporção nunca passava do limiar.
 *
 * O sinal certo é outro: a síntese de um LLM é curta (2 a 3 parágrafos) e não
 * carrega marca de conversa. O digest é longo e vem cheio de "O Arquiteto
 * disse", "Conclusão do assistente" — o carimbo de quem gravou a memória.
 */
function ehDigest(bruto: string): boolean {
  const t = bruto || "";
  if (t.length < 400) return false;                       // síntese é curta
  const marcas = (t.match(/O Arquiteto disse|Conclus[ãa]o do assistente|sess[ãa]o Claude Code/gi) || []).length;
  const traços = (t.match(/^[-•]\s/gm) || []).length;
  return marcas >= 2 || traços >= 4;
}

export default function InsightList({ text }: { text: string }) {
  const linhas = limpar(text);
  if (!linhas.length) return null;
  const digest = ehDigest(text);

  return (
    <div className="rounded-[13px] p-3 panel-grad">
      {digest && (
        <div className="flex items-start gap-2 px-2 pb-2.5 mb-1 border-b border-[var(--line)] text-[12px] text-[var(--dim)]">
          <Info size={12} className="mt-[3px] flex-none" />
          <span>
            Sem um modelo configurado, isto é o que foi <b>lembrado recentemente</b> — não uma
            síntese. Ligue um LLM em Configurações e esta seção passa a concluir, em vez de listar.
          </span>
        </div>
      )}
      {/* Teto de 12: a lista existe para dar um retrato, não para ser lida
          inteira. Sem o corte, um digest de 30 linhas empurra o resto da tela
          para fora da primeira dobra. */}
      {linhas.slice(0, 12).map((l, i) => (
        <div key={i} className="flex items-start gap-2.5 px-2 py-2 rounded-lg hover:bg-white/[0.03]">
          <Sparkles size={13} className="text-[var(--accent2)] mt-[3px] flex-none" />
          <Markdown text={l} className="text-[14px] leading-relaxed min-w-0" />
        </div>
      ))}
      {linhas.length > 12 && (
        <div className="px-2 pt-1 text-[11.5px] text-[var(--dim)]">
          e mais {linhas.length - 12} — a lista completa está em Memórias.
        </div>
      )}
    </div>
  );
}
