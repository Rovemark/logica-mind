/** NEURÔNIO — o nó do grafo como célula que EMITE luz.
 *
 *  A versão anterior desenhava o objeto errado: uma bola de vidro iluminada POR
 *  FORA (reflexo especular, aro fresnel, faixas internas, luz de retorno). Toda
 *  aquela luz era BRANCA, e branco sobre cor mata a cor: #7c9cff, saturação 100%,
 *  virava (186,187,190) — saturação 1,4%. Cinza-pérola. Bonito e morto.
 *
 *  Aqui o objeto é outro: uma célula emissiva, composta em modo ADITIVO, onde a
 *  cor vem da escada de 4 degraus no mesmo matiz (ver lib/color.ts). O mesmo
 *  pixel do exemplo acima agora sai (125,157,252): saturação 97%.
 *
 *  DUAS PARTES:
 *   · SOMA    — o corpo da célula. 5 stops + membrana. Nunca branco.
 *   · CORONA  — o halo. Como as duas são aditivas e a corona vai por baixo, um nó
 *               aceso recebe corona + soma no centro e ESTOURA para branco-quente
 *               sozinho, pela física — sem uma gota de tinta branca. É o "acende"
 *               do HUD. O nó apagado nunca estoura.
 *
 *  Custo: os gradientes são pagos UMA vez por (matiz, tier, tema) num canvas fora
 *  da tela; por nó, por quadro, o desenho é um drawImage. Matiz quantizado em 24
 *  baldes × 3 tiers × 2 temas = 144 sprites no teto, com LRU.
 */

import { ladderFor, hueBucket, hueOfHex } from "./color";

const SOMA = 72;
const CORONA = 96;
const TETO = 256;                                  // LRU: nunca vira vazamento

const cacheSoma = new Map<string, HTMLCanvasElement>();
const cacheCorona = new Map<string, HTMLCanvasElement>();

function lru(m: Map<string, HTMLCanvasElement>, k: string, faz: () => HTMLCanvasElement) {
  const hit = m.get(k);
  if (hit) { m.delete(k); m.set(k, hit); return hit; }   // renova a idade
  const cv = faz();
  m.set(k, cv);
  if (m.size > TETO) m.delete(m.keys().next().value as string);
  return cv;
}

/** Corpo da célula: a escada emissiva num único gradiente, mais a membrana. */
function soma(h: number, tier: number, light: boolean): HTMLCanvasElement {
  return lru(cacheSoma, `${h}|${tier}|${light ? "L" : "D"}`, () => {
    const cv = document.createElement("canvas");
    cv.width = cv.height = SOMA;
    const c = cv.getContext("2d")!;
    const C = SOMA / 2, R = C - 3;
    const L = ladderFor(h, tier, light);
    const rgb = (i: number) => L[i].join(",");
    // dentro do sprite a composição é sempre aditiva: o sprite é a IMAGEM da luz.
    // Quem traduz pro tema (lighter vs multiply) é o desenho no grafo.
    c.globalCompositeOperation = "lighter";

    // (1) CORPO — 5 stops, borda MOLE. A queda é calibrada no HUD (1.0 → 0.4 no
    //     primeiro quarto), só que mais íngreme: em 2D cada nó é uma nuvem e a
    //     densidade do grafo é bem maior que a da nuvem 3D dele.
    const g1 = c.createRadialGradient(C, C, 0, C, C, R);
    g1.addColorStop(0.00, `rgba(${rgb(0)},1)`);
    g1.addColorStop(0.22, `rgba(${rgb(1)},.88)`);
    g1.addColorStop(0.55, `rgba(${rgb(2)},.50)`);
    g1.addColorStop(0.85, `rgba(${rgb(3)},.16)`);
    g1.addColorStop(1.00, `rgba(${rgb(3)},0)`);
    c.fillStyle = g1;
    c.beginPath(); c.arc(C, C, R, 0, 6.283); c.fill();

    // (2) MEMBRANA — o único traço "duro" do sistema, e ainda assim mole. É ela
    //     que separa CÉLULA de borrão. Em COR, jamais em branco: o aro fresnel
    //     antigo era exatamente isto, só que branco — a ideia estava certa, a cor
    //     é que destruía a identidade do nó.
    c.strokeStyle = `rgba(${rgb(2)},${[0.34, 0.46, 0.60][tier]})`;
    c.lineWidth = R * 0.085;
    c.beginPath(); c.arc(C, C, R * 0.86, 0, 6.283); c.stroke();

    return cv;
  });
}

/** Halo. Queda brutal no primeiro décimo + saia longa quase invisível — é esse
 *  perfil que faz "luz emitida" em vez de "disco borrado". Não depende de tier. */
function corona(h: number, light: boolean): HTMLCanvasElement {
  return lru(cacheCorona, `${h}|${light ? "L" : "D"}`, () => {
    const cv = document.createElement("canvas");
    cv.width = cv.height = CORONA;
    const c = cv.getContext("2d")!;
    const C = CORONA / 2;
    const e = ladderFor(h, 1, light)[light ? 2 : 1].join(",");
    const g = c.createRadialGradient(C, C, 0, C, C, C);
    g.addColorStop(0.00, `rgba(${e},1)`);
    g.addColorStop(0.10, `rgba(${e},.55)`);
    g.addColorStop(0.25, `rgba(${e},.22)`);
    g.addColorStop(0.45, `rgba(${e},.075)`);
    g.addColorStop(0.70, `rgba(${e},.02)`);
    g.addColorStop(1.00, `rgba(${e},0)`);
    c.fillStyle = g;
    c.fillRect(0, 0, CORONA, CORONA);
    return cv;
  });
}

export interface OrbOpts {
  tier?: 0 | 1 | 2;
  glow?: number;        // 0..1 — intensidade da corona
  coronaR?: number;     // múltiplo do raio (1.9 normal · 2.3 vizinho · 3.0 foco)
  somaA?: number;       // 0..1 — piso duro de 0.34: abaixo disso a topologia some
  pulse?: number;       // 0..1 — respiração da corona
  light?: boolean;
  rTela?: number;       // raio em px de TELA, só pra decidir nível de detalhe
}

/** Desenha o neurônio. O modo de composição é escolhido pelo TEMA:
 *  escuro → `lighter` (somar luz) · claro → `multiply` (densar tinta). */
export function drawOrb(
  c: CanvasRenderingContext2D,
  x: number, y: number, r: number,
  hex: string,
  o: OrbOpts = {},
) {
  const light = !!o.light;
  const h = hueBucket(hueOfHex(hex));
  const tier = (o.tier ?? 0) as 0 | 1 | 2;
  const glow = o.glow ?? 0;
  const somaA = o.somaA ?? 1;
  const rTela = o.rTela ?? r;
  const modo = light ? "multiply" : "lighter";

  // Abaixo de ~1.4px de tela nenhum detalhe é visível: um ponto na cor já
  // resolvida é honesto e mais barato. Detalhe que ninguém vê é só custo.
  if (rTela < 1.4 && glow <= 0) {
    c.save();
    c.globalCompositeOperation = modo;
    c.globalAlpha = somaA;
    c.fillStyle = `rgb(${ladderFor(h, tier, light)[2].join(",")})`;
    c.beginPath(); c.arc(x, y, r, 0, 6.283); c.fill();
    c.restore();
    return;
  }

  c.save();
  c.globalCompositeOperation = modo;
  if (glow > 0) {
    const hr = r * (o.coronaR ?? 1.9) * (1 + 0.16 * (o.pulse ?? 0));
    c.globalAlpha = glow;
    c.drawImage(corona(h, light), x - hr, y - hr, hr * 2, hr * 2);
  }
  c.globalAlpha = somaA;
  c.drawImage(soma(h, tier, light), x - r, y - r, r * 2, r * 2);
  c.restore();
}

/** Descarta os sprites — obrigatório na virada de tema, já que a escada inteira
 *  (e o operador de composição) mudam com ele. */
export function resetOrbs() {
  cacheSoma.clear();
  cacheCorona.clear();
}
