// Formatação de NÚMERO para leitura humana.
//
// PERGUNTA que responde: "são 8 mil ou 80 mil?"
// O painel mostrava "85267". Ninguém lê 5 dígitos crus de relance — o olho tem
// que contar as casas. Com o ponto de milhar ("85.267") a ordem de grandeza
// entra na hora, que é a única coisa que o dono realmente lê nesse cartão.
//
// pt-BR sempre (regra da casa: tudo em pt-BR), e o formatter é criado UMA vez —
// Intl.NumberFormat é caro pra instanciar e estes contadores re-renderizam a
// cada 8s.
const NUM = new Intl.NumberFormat("pt-BR");

/** 85267 → "85.267". Devolve "—" para nulo/NaN: "ainda não sei" nunca deve
 *  virar "0", que é uma AFIRMAÇÃO (e, num appliance de memória, uma mentira
 *  alarmante). */
export function num(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return NUM.format(v);
}

/** Latência legível. 850 → "850ms"; 19153.7 → "19,2s".
 *
 *  PERGUNTA: "isso é rápido ou é um problema?"
 *  "19153.7ms" era ilegível DUAS vezes: o número não cabia no cartão (aparecia
 *  cortado, "19153.7m") e milissegundos acima de mil não têm escala mental.
 *  Acima de 1s o valor vira segundos com 1 casa — cabe, e a resposta é imediata.
 *  Não muda dado nenhum: é a mesma medida, escrita para ser lida. */
export function ms(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  if (v < 1000) return `${Math.round(v)}ms`;
  return `${(v / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}s`;
}
