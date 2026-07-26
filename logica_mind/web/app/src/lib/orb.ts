/** Esfera de vidro — a linguagem visual do HUD trazida pro grafo.
 *
 *  O nó deixa de ser um disco chapado e passa a ler como ESFERA TRANSLÚCIDA: luz
 *  entrando pelo alto-esquerda, corpo que deixa ver o que está atrás, faixas
 *  internas de luz, aro de borda (fresnel) e um reflexo especular. Selecionado,
 *  ganha o halo do HUD — núcleo quente + brilho largo.
 *
 *  POR QUE SPRITE, e não desenhar direto no grafo:
 *  cada esfera são ~7 gradientes. Fazer isso por nó, por quadro, com milhares de
 *  nós, derreteria a CPU — e o grafo existe pra aguentar milhares. Aqui o custo é
 *  pago UMA vez por cor, guardado num canvas fora da tela; o desenho por nó vira
 *  um `drawImage`, tão barato quanto a bolinha chapada que havia antes. A beleza
 *  não entra às custas da fluidez.
 */

const CORPO = 128;   // resolução do sprite do corpo — nítido até ~64px de raio na tela
const HALO = 160;    // o halo é mais borrado, tolera menos resolução

const cacheCorpo = new Map<string, HTMLCanvasElement>();
const cacheHalo = new Map<string, HTMLCanvasElement>();

function rgbOf(hex: string): [number, number, number] {
  const h = String(hex || "#7c9cff").replace("#", "");
  const s = h.length === 3 ? h.split("").map((x) => x + x).join("") : h;
  const n = parseInt(s.slice(0, 6), 16);
  return Number.isFinite(n) ? [(n >> 16) & 255, (n >> 8) & 255, n & 255] : [124, 156, 255];
}

/** Corpo da esfera: vidro translúcido com volume. */
export function orbBody(hex: string, light = false): HTMLCanvasElement {
  const key = hex + (light ? "L" : "D");
  const hit = cacheCorpo.get(key);
  if (hit) return hit;

  const cv = document.createElement("canvas");
  cv.width = cv.height = CORPO;
  const c = cv.getContext("2d")!;
  const [r, g, b] = rgbOf(hex);
  const C = CORPO / 2, R = C - 2;
  const rgba = (a: number) => `rgba(${r},${g},${b},${a})`;
  // no tema claro o vidro precisa de mais corpo, senão some no fundo Ivory
  const dens = light ? 1.45 : 1;

  // 1. CORPO — o gradiente é deslocado pro alto-esquerda: é isso que faz o olho
  //    ler esfera em vez de disco. Clareia onde a luz entra e afina até quase
  //    transparente na borda, deixando as arestas do grafo aparecerem por trás.
  c.beginPath(); c.arc(C, C, R, 0, 6.283);
  const corpo = c.createRadialGradient(C - R * 0.34, C - R * 0.40, R * 0.04, C, C, R);
  const clar = (v: number) => Math.min(255, (v + 255 * 2) / 3 | 0);   // mistura 2/3 branco
  corpo.addColorStop(0, `rgba(255,255,255,${0.70 * (light ? 0.8 : 1)})`);
  corpo.addColorStop(0.18, `rgba(${clar(r)},${clar(g)},${clar(b)},.56)`);
  corpo.addColorStop(0.55, rgba(Math.min(0.92, 0.42 * dens)));
  corpo.addColorStop(0.86, rgba(Math.min(0.85, 0.24 * dens)));
  corpo.addColorStop(1, rgba(Math.min(0.75, 0.13 * dens)));
  c.fillStyle = corpo; c.fill();

  // 2. FAIXAS INTERNAS — as ondas de luz que atravessam o vidro na referência.
  //    Recortadas na esfera pra não vazar; aditivas pra somarem luz, não tinta.
  c.save();
  c.beginPath(); c.arc(C, C, R, 0, 6.283); c.clip();
  c.globalCompositeOperation = "lighter";
  const faixas = [
    { rot: -0.52, rx: 0.94, ry: 0.42, dy: -0.10, a: 0.17 },
    { rot: 0.85, rx: 0.80, ry: 0.30, dy: 0.20, a: 0.12 },
  ];
  for (const f of faixas) {
    c.save();
    c.translate(C, C + R * f.dy); c.rotate(f.rot);
    c.beginPath(); c.ellipse(0, 0, R * f.rx, R * f.ry, 0, 0, 6.283);
    const sw = c.createLinearGradient(-R, 0, R, 0);
    sw.addColorStop(0, "rgba(255,255,255,0)");
    sw.addColorStop(0.45, `rgba(255,255,255,${f.a})`);
    sw.addColorStop(1, "rgba(255,255,255,0)");
    c.strokeStyle = sw; c.lineWidth = R * 0.14; c.stroke();
    c.restore();
  }
  c.restore();

  // 3. ARO DE BORDA (fresnel) — vidro acende na beirada OPOSTA à fonte de luz.
  //    É esse fio claro embaixo-à-direita que separa "esfera de vidro" de "bolha".
  c.beginPath(); c.arc(C, C, R * 0.965, 0, 6.283);
  const aro = c.createLinearGradient(C - R, C - R, C + R, C + R);
  aro.addColorStop(0, "rgba(255,255,255,.05)");
  aro.addColorStop(0.45, rgba(0.30));
  aro.addColorStop(0.80, `rgba(255,255,255,${light ? 0.5 : 0.62})`);
  aro.addColorStop(1, "rgba(255,255,255,.28)");
  c.strokeStyle = aro; c.lineWidth = R * 0.085; c.stroke();

  // 4. REFLEXO ESPECULAR — o ponto de luz. Sem ele, nada lê como esfera.
  c.save();
  c.translate(C - R * 0.34, C - R * 0.40); c.rotate(-0.5);
  c.beginPath(); c.ellipse(0, 0, R * 0.30, R * 0.19, 0, 0, 6.283);
  const esp = c.createRadialGradient(0, 0, 0, 0, 0, R * 0.30);
  esp.addColorStop(0, "rgba(255,255,255,.92)");
  esp.addColorStop(0.55, "rgba(255,255,255,.34)");
  esp.addColorStop(1, "rgba(255,255,255,0)");
  c.fillStyle = esp; c.fill();
  c.restore();

  // 5. LUZ DE RETORNO — o que a superfície interna devolve embaixo. Fecha o volume.
  const bx = C + R * 0.20, by = C + R * 0.44;
  c.beginPath(); c.ellipse(bx, by, R * 0.36, R * 0.17, 0.3, 0, 6.283);
  const bl = c.createRadialGradient(bx, by, 0, bx, by, R * 0.36);
  bl.addColorStop(0, "rgba(255,255,255,.20)");
  bl.addColorStop(1, "rgba(255,255,255,0)");
  c.fillStyle = bl; c.fill();

  cacheCorpo.set(key, cv);
  return cv;
}

/** Halo de seleção na gramática do HUD: núcleo quente + brilho largo. Sprite
 *  separado do corpo pra que o pulso escale SÓ o brilho, sem inchar a esfera. */
export function orbHalo(hex: string): HTMLCanvasElement {
  const hit = cacheHalo.get(hex);
  if (hit) return hit;

  const cv = document.createElement("canvas");
  cv.width = cv.height = HALO;
  const c = cv.getContext("2d")!;
  const [r, g, b] = rgbOf(hex);
  const C = HALO / 2;
  const rgba = (a: number) => `rgba(${r},${g},${b},${a})`;

  const gr = c.createRadialGradient(C, C, 0, C, C, C);
  gr.addColorStop(0, "rgba(255,255,255,.50)");   // núcleo quente (o `0 0 12px` do HUD)
  gr.addColorStop(0.13, rgba(0.52));
  gr.addColorStop(0.33, rgba(0.22));
  gr.addColorStop(0.62, rgba(0.07));             // halo largo (o `0 0 40px`)
  gr.addColorStop(1, rgba(0));
  c.fillStyle = gr;
  c.fillRect(0, 0, HALO, HALO);

  cacheHalo.set(hex, cv);
  return cv;
}

/** Desenha a esfera. `glow` 0..1 acende o halo; `pulse` 0..1 respira o raio dele.
 *  `rTela` é o raio JÁ em pixels de tela — usado só pra decidir o nível de detalhe. */
export function drawOrb(
  c: CanvasRenderingContext2D,
  x: number, y: number, r: number,
  hex: string,
  o?: { glow?: number; pulse?: number; light?: boolean; rTela?: number },
) {
  const glow = o?.glow || 0;
  const rTela = o?.rTela ?? r;

  // Abaixo de ~1.6px na tela nenhum detalhe é visível: um ponto chapado é
  // honesto e mais barato. Detalhe que ninguém vê é só custo.
  if (rTela < 1.6 && glow <= 0) {
    c.beginPath(); c.arc(x, y, r, 0, 6.283);
    c.fillStyle = hex; c.fill();
    return;
  }

  if (glow > 0) {
    const hr = r * (2.5 + 0.45 * (o?.pulse ?? 0));
    c.save();
    c.globalCompositeOperation = "lighter";
    c.globalAlpha = Math.min(1, glow);
    c.drawImage(orbHalo(hex), x - hr, y - hr, hr * 2, hr * 2);
    c.restore();
  }
  c.drawImage(orbBody(hex, o?.light), x - r, y - r, r * 2, r * 2);
}

/** Descarta os sprites — chamar na troca de tema, já que o corpo é calibrado por tema. */
export function resetOrbs() {
  cacheCorpo.clear();
  cacheHalo.clear();
}
