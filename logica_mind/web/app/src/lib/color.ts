/** A escada emissiva — o modelo de luz do HUD do Jarvis, portado pro Canvas 2D.
 *
 *  A ideia central, tirada dos tokens do HUD: um nó não tem UMA cor, tem uma
 *  ESCADA de 4 degraus no MESMO matiz, e o raio percorre a escada do miolo
 *  quente até a casca profunda (--white-hot → --ember-hot → --ember → --ember-deep).
 *
 *  REGRA PERMANENTE: branco puro é proibido em nó e aresta. Ele é o que lavou a
 *  versão anterior — #7c9cff (saturação 100%) virava (186,187,190), saturação
 *  1,4%: cinza. Branco só é permitido como hsl(matiz, 40%, 88%) — branco TINGIDO
 *  pelo matiz, que continua legível como "aquele é o nó azul" mesmo estourado.
 */

// ── conversões ──────────────────────────────────────────────────────────────
export function hexToRgb(hex: string): [number, number, number] {
  const h = String(hex || "#7c9cff").replace("#", "");
  const s = h.length === 3 ? h.split("").map((x) => x + x).join("") : h;
  const n = parseInt(s.slice(0, 6), 16);
  return Number.isFinite(n) ? [(n >> 16) & 255, (n >> 8) & 255, n & 255] : [124, 156, 255];
}

export function hsl2rgb(h: number, s: number, l: number): [number, number, number] {
  const c = (1 - Math.abs(2 * l - 1)) * s, hp = (((h % 360) + 360) % 360) / 60;
  const x = c * (1 - Math.abs((hp % 2) - 1)), m = l - c / 2;
  const t = [[c, x, 0], [x, c, 0], [0, c, x], [0, x, c], [x, 0, c], [c, 0, x]][Math.floor(hp) % 6];
  return [((t[0] + m) * 255) | 0, ((t[1] + m) * 255) | 0, ((t[2] + m) * 255) | 0];
}

/** Matiz de uma cor. É só o matiz que sobrevive: a escada refaz saturação e
 *  luminância, porque o que lava a cor é justamente herdar S e L baixos. */
export function hueOf(rgb: [number, number, number]): number {
  const [r, g, b] = rgb.map((v) => v / 255) as [number, number, number];
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  if (d < 1e-6) return 225;                       // cinza → azul do sistema
  let h: number;
  if (mx === r) h = ((g - b) / d) % 6;
  else if (mx === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  return (((h * 60) % 360) + 360) % 360;
}

// memo: hueOf + parse por string de cor. As cores vêm das mesmas paletas o tempo
// todo, então isso converge pra um punhado de entradas.
const memoHue = new Map<string, number>();
export function hueOfHex(hex: string): number {
  const hit = memoHue.get(hex);
  if (hit !== undefined) return hit;
  const h = hueOf(hexToRgb(hex));
  memoHue.set(hex, h);
  return h;
}

// ── a escada ────────────────────────────────────────────────────────────────
type RGB = [number, number, number];

/** TEMA ESCURO — aditivo. tier: 0=folha 1=média 2=hub.
 *  Só o degrau 0 (o miolo) muda por tier: é assim que a hierarquia entra sem
 *  gastar uma camada nem uma chamada de desenho a mais.
 *  A FOLHA NÃO CHEGA AO BRANCO — hsl(225,82%,66%) é periwinkle vivo, não pérola.
 *  Antes todo nó tinha o mesmo miolo branco, independente de importância. */
export const LADDER = (h: number, tier: number): RGB[] => [
  hsl2rgb(h, [0.82, 0.60, 0.40][tier], [0.66, 0.78, 0.88][tier]),  // --white-hot (só o hub chega lá)
  hsl2rgb(h, 0.78, 0.70),                                          // --ember-hot
  hsl2rgb(h, 0.92, 0.60),                                          // --ember
  hsl2rgb(h, 0.95, 0.44),                                          // --ember-deep
];

/** TEMA CLARO — multiply. O dual honesto, não a mesma receita com outro alpha.
 *  Aditivo sobre papel (244,241,234) é matematicamente morto: satura em qualquer
 *  canal. Sobre fundo claro, "luminoso" quer dizer mais DENSO e mais CROMÁTICO —
 *  vitral, não LED. E multiply de uma cor por ela mesma AUMENTA a saturação (o
 *  canal baixo encolhe mais rápido que o alto), que é o dual exato do "aditivo
 *  clipa pra branco". Por isso a escada inverte: miolo escuro, casca clara. */
export const LADDER_LIGHT = (h: number, tier: number): RGB[] => [
  hsl2rgb(h, [0.98, 0.98, 1.00][tier], [0.38, 0.33, 0.28][tier]),  // miolo: a tinta mais densa
  hsl2rgb(h, 0.92, 0.42),
  hsl2rgb(h, 0.78, 0.50),
  hsl2rgb(h, 0.55, 0.62),                                          // casca: sangria clara
];

export const ladderFor = (h: number, tier: number, light: boolean) =>
  light ? LADDER_LIGHT(h, tier) : LADDER(h, tier);

/** Quantiza o matiz em 24 baldes. É o que segura o cache de sprites: sem isso,
 *  cada cor distinta vira um canvas novo e a memória cresce sem teto. */
export const hueBucket = (h: number) => Math.round(h / 15) * 15;

/** Creme quente — RESERVADO a dois usos e mais nada: o nó em foco e a faísca da
 *  sinapse. O HUD faz igual ("o que está vivo é quase-branco quente, foge do
 *  matiz de propósito"). Se creme aparece em tudo, deixa de significar "vivo". */
export const CREME = "255,240,200";

export function clearColorCache() { memoHue.clear(); }
