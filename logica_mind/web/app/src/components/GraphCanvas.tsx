import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { PALETTE, type GraphData } from "../api";

export interface GraphHandle { reheat: () => void; fit: () => void; center: (id: string) => void; }

// edge grammar: relations are hued by their predicate CLASS (so the graph reads
// like a sentence, not a tangle of identical blue lines); emergent layers get
// their own cool, low-contrast treatment.
const PCLASS_RGB: Record<string, string> = {
  social: "245,158,11", has: "74,222,128", causal: "251,113,133",
  locative: "34,211,238", temporal: "167,139,250", is_a: "124,156,255", other: "148,163,184",
};
const COMENTION_RGB = "120,140,170";   // dashed — "talked about together"
const SEMANTIC_RGB = "150,130,200";    // dotted — latent affinity

// node radius scales with PageRank centrality, so hubs read as hubs
function baseRad(n: any, hover: boolean): number {
  return 4 + (n.centrality || 0) * 6 + (n.shared ? 1.5 : 0) + (hover ? 3 : 0);
}

interface Props {
  data: GraphData;
  communities: boolean;
  colorFor: (ns: string) => string;
  onPick: (name: string) => void;
  // optional per-node tint (e.g. colour by life-area). Returning null falls back
  // to the default namespace/shared colouring.
  nodeTint?: (n: any) => string | null;
}

// Live canvas force-simulation (Obsidian-style continuous physics):
// repulsion + spring + gravity with damping + alpha cooling; reheats on
// interaction. Pan/zoom/drag with mouse AND touch (pinch-zoom). A click/tap on a
// node calls onPick(name) so the parent can show its memories + relations.
const GraphCanvas = forwardRef<GraphHandle, Props>(function GraphCanvas(
  { data, communities, colorFor, onPick, nodeTint }, ref,
) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const commRef = useRef(communities);
  const colorRef = useRef(colorFor);
  const pickRef = useRef(onPick);
  const tintRef = useRef(nodeTint);
  commRef.current = communities;
  colorRef.current = colorFor;
  pickRef.current = onPick;
  tintRef.current = nodeTint;

  const G = useRef<any>({ nodes: [], links: [], byId: {}, adj: {}, comp: {}, t: { x: 0, y: 0, k: 1 }, hover: null, drag: null, alpha: 0, raf: 0, W: 0, H: 0, dpr: 1, fitOnce: false });

  useImperativeHandle(ref, () => ({
    reheat: () => { G.current.alpha = 1; },
    fit: () => fitGraph(true),
    // pan/zoom to a node and highlight it (used by search-focus + backlink jumps)
    center: (id: string) => {
      const g = G.current, n = g.byId[id]; if (!n) return;
      const k = Math.max(g.t.k, 1.25);
      const s = { ...g.t }, tx = g.W / 2 - n.x * k, ty = g.H / 2 - n.y * k, st = performance.now();
      g.hover = id;
      const an = () => { const p = Math.min(1, (performance.now() - st) / 350), e = 1 - Math.pow(1 - p, 3);
        g.t = { x: s.x + (tx - s.x) * e, y: s.y + (ty - s.y) * e, k: s.k + (k - s.k) * e }; if (p < 1) requestAnimationFrame(an); }; an();
    },
  }));

  function computeComponents() {
    const g = G.current, p: Record<string, string> = {};
    const find = (x: string): string => { p[x] = p[x] || x; while (p[x] !== x) { p[x] = p[p[x]]; x = p[x]; } return x; };
    g.nodes.forEach((n: any) => (p[n.id] = n.id));
    g.links.forEach((l: any) => { const a = find(l.source), b = find(l.target); if (a !== b) p[a] = b; });
    const roots: Record<string, number> = {}; let ci = 0; g.comp = {};
    g.nodes.forEach((n: any) => { const r = find(n.id); if (!(r in roots)) roots[r] = ci++; g.comp[n.id] = roots[r]; });
  }
  function setupCanvas() {
    const g = G.current, cv = canvasRef.current!, wrap = wrapRef.current!;
    g.dpr = window.devicePixelRatio || 1;
    const r = wrap.getBoundingClientRect(); g.W = r.width; g.H = r.height;
    cv.width = g.W * g.dpr; cv.height = g.H * g.dpr; cv.style.width = g.W + "px"; cv.style.height = g.H + "px";
    g.ctx = cv.getContext("2d"); g.ctx.scale(g.dpr, g.dpr);
  }
  function nodeColor(n: any) {
    const g = G.current;
    if (commRef.current) return PALETTE[(g.comp[n.id] || 0) % PALETTE.length];
    if (tintRef.current) { const t = tintRef.current(n); if (t) return t; }
    if (n.shared) return "#fbbf24";
    return colorRef.current((n.namespaces && n.namespaces[0]) || "");
  }
  function tick() {
    const g = G.current, N = g.nodes.length; if (!N) return;
    const K = Math.max(48, 230 / Math.sqrt(N)), a = g.alpha;
    for (let i = 0; i < N; i++) { const A = g.nodes[i]; for (let k = i + 1; k < N; k++) { const B = g.nodes[k];
      let dx = A.x - B.x, dy = A.y - B.y, d2 = dx * dx + dy * dy || 0.01, dist = Math.sqrt(d2), rep = (K * K) / d2 * a * 0.9, ux = dx / dist, uy = dy / dist;
      A.vx += ux * rep; A.vy += uy * rep; B.vx -= ux * rep; B.vy -= uy * rep; } }
    g.links.forEach((l: any) => { const A = g.byId[l.source], B = g.byId[l.target]; if (!A || !B) return;
      let dx = B.x - A.x, dy = B.y - A.y, dist = Math.hypot(dx, dy) || 0.01, f = (dist - K) * 0.04 * a, ux = dx / dist, uy = dy / dist;
      A.vx += ux * f; A.vy += uy * f; B.vx -= ux * f; B.vy -= uy * f; });
    g.nodes.forEach((n: any) => {
      n.vx += -n.x * 0.004 * a; n.vy += -n.y * 0.004 * a;
      if (n.fx != null) { n.x = n.fx; n.y = n.fy; n.vx = n.vy = 0; return; }
      n.vx *= 0.86; n.vy *= 0.86; n.x += n.vx; n.y += n.vy;
    });
    g.alpha *= 0.985; if (g.alpha < 0.004) g.alpha = 0;
  }
  function draw() {
    const g = G.current, c = g.ctx; if (!c) return; const t = g.t;
    c.clearRect(0, 0, g.W, g.H); c.save(); c.translate(t.x, t.y); c.scale(t.k, t.k);
    const hi = g.hover, nbr = hi ? (g.adj[hi] || new Set()) : null;
    // theme-aware ink so labels/edges read on both the light and dark canvas
    const light = document.documentElement.getAttribute("data-theme") === "light";
    const edgeDead = light ? "rgba(120,130,150,.35)" : "rgba(90,100,120,.28)";
    const labelFill = light ? "#1f2940" : "#e8eef7", labelFillDim = light ? "#8a93a6" : "#5a6477";
    const labelStroke = light ? "rgba(255,255,255,.9)" : "#0a0d14";
    const edgeLabel = light ? "rgba(70,82,110,.7)" : "rgba(150,165,190,.65)";
    const nodeRing = (shared: boolean) => shared ? (light ? "rgba(60,80,160,.55)" : "rgba(255,255,255,.55)")
                                                 : (light ? "rgba(40,55,90,.3)" : "rgba(10,13,20,.9)");
    g.links.forEach((l: any) => { const A = g.byId[l.source], B = g.byId[l.target]; if (!A || !B) return;
      const active = !hi || l.source === hi || l.target === hi;
      const kind = l.kind || "relation";
      const mx = (A.x + B.x) / 2, my = (A.y + B.y) / 2 - Math.hypot(B.x - A.x, B.y - A.y) * 0.07;
      c.beginPath(); c.moveTo(A.x, A.y); c.quadraticCurveTo(mx, my, B.x, B.y);
      let rgb: string, alpha: number, width: number, dash: number[] | null = null, arrow = false;
      if (kind === "co_mention") {
        rgb = COMENTION_RGB; alpha = active ? 0.5 : 0.16; dash = [4, 4];
        width = 0.7 + Math.min(l.weight || 1, 5) * 0.26;
      } else if (kind === "semantic") {
        rgb = SEMANTIC_RGB; alpha = active ? 0.45 : 0.13; width = 0.8; dash = [1.2, 4];
      } else {                                            // relation, hued by predicate class
        const conf = l.confidence == null ? 1 : l.confidence;
        if (!l.valid) {                                   // superseded — greyed + dashed, no arrow
          c.strokeStyle = edgeDead; c.lineWidth = (0.6 + 1.2 * conf) / Math.sqrt(t.k);
          c.setLineDash([5 / t.k, 4 / t.k]); c.stroke(); c.setLineDash([]);
          if (t.k > 0.85 && active && l.label) { c.fillStyle = edgeLabel; c.font = `${10 / t.k}px -apple-system,sans-serif`; c.textAlign = "center"; c.fillText(l.label, mx, my - 3 / t.k); }
          return;
        }
        rgb = PCLASS_RGB[l.pclass || "other"] || PCLASS_RGB.other;
        alpha = active ? 0.3 + 0.55 * conf : 0.12; width = 0.7 + 1.8 * conf; arrow = true;
      }
      c.strokeStyle = `rgba(${rgb},${alpha})`;
      c.lineWidth = width / Math.sqrt(t.k);
      if (dash) c.setLineDash(dash.map((d) => d / t.k));
      c.stroke(); c.setLineDash([]);
      if (arrow && t.k > 0.7 && active) {                 // directional arrowhead at the target
        const ang = Math.atan2(B.y - my, B.x - mx);
        const br = baseRad(B, false) / Math.sqrt(t.k);
        const tx = B.x - Math.cos(ang) * (br + 1.5 / t.k), ty = B.y - Math.sin(ang) * (br + 1.5 / t.k);
        const s = 5 / t.k;
        c.beginPath(); c.moveTo(tx, ty);
        c.lineTo(tx - s * Math.cos(ang - 0.42), ty - s * Math.sin(ang - 0.42));
        c.lineTo(tx - s * Math.cos(ang + 0.42), ty - s * Math.sin(ang + 0.42));
        c.closePath(); c.fillStyle = `rgba(${rgb},${active ? 0.85 : 0.3})`; c.fill();
      }
      if (t.k > 0.85 && active && l.label) { c.fillStyle = edgeLabel; c.font = `${10 / t.k}px -apple-system,sans-serif`; c.textAlign = "center"; c.fillText(l.label, mx, my - 3 / t.k); }
    });
    g.nodes.forEach((n: any) => { const active = !hi || n.id === hi || (nbr && nbr.has(n.id));
      const col = nodeColor(n), rad = baseRad(n, n.id === hi);
      if (n.id === hi || (nbr && nbr.has(n.id))) { c.beginPath(); c.arc(n.x, n.y, rad + 7 / t.k, 0, 6.283); c.fillStyle = col + "33"; c.fill(); }
      c.beginPath(); c.arc(n.x, n.y, rad / Math.sqrt(t.k), 0, 6.283);
      c.fillStyle = active ? col : col + "44"; c.fill();
      c.lineWidth = (n.shared ? 2 : 1.4) / t.k; c.strokeStyle = nodeRing(!!n.shared); c.stroke();
      if (t.k > 0.6 && active) { c.fillStyle = active ? labelFill : labelFillDim; c.font = `${11 / t.k}px -apple-system,sans-serif`; c.textAlign = "center";
        c.lineWidth = 3 / t.k; c.strokeStyle = labelStroke; c.strokeText(n.id, n.x, n.y - (rad + 5) / t.k); c.fillText(n.id, n.x, n.y - (rad + 5) / t.k); }
    });
    c.restore();
  }
  function fitGraph(animate: boolean) {
    const g = G.current; if (!g.nodes.length) return;
    let a = 1e9, b = 1e9, cc = -1e9, d = -1e9;
    g.nodes.forEach((n: any) => { a = Math.min(a, n.x); b = Math.min(b, n.y); cc = Math.max(cc, n.x); d = Math.max(d, n.y); });
    const w = cc - a || 1, h = d - b || 1, pad = 70, k = Math.min((g.W - pad * 2) / w, (g.H - pad * 2) / h, 1.8);
    const tx = g.W / 2 - ((a + cc) / 2) * k, ty = g.H / 2 - ((b + d) / 2) * k;
    if (animate) { const s = { ...g.t }, st = performance.now();
      const an = () => { const p = Math.min(1, (performance.now() - st) / 350), e = 1 - Math.pow(1 - p, 3);
        g.t = { x: s.x + (tx - s.x) * e, y: s.y + (ty - s.y) * e, k: s.k + (k - s.k) * e }; if (p < 1) requestAnimationFrame(an); }; an();
    } else g.t = { x: tx, y: ty, k };
  }
  function nodeAt(cx: number, cy: number) {
    const g = G.current, x = (cx - g.t.x) / g.t.k, y = (cy - g.t.y) / g.t.k; let best: any = null, bd = 14 / g.t.k;
    g.nodes.forEach((n: any) => { const dd = Math.hypot(n.x - x, n.y - y); if (dd < bd) { bd = dd; best = n; } }); return best;
  }

  // (re)build the simulation whenever the graph data changes
  useEffect(() => {
    const g = G.current, cv = canvasRef.current; if (!cv) return;
    if (g.raf) cancelAnimationFrame(g.raf);
    const old: Record<string, any> = {}; (g.nodes || []).forEach((n: any) => (old[n.id] = { x: n.x, y: n.y, vx: n.vx, vy: n.vy }));
    g.nodes = (data.nodes || []).map((n, i) => { const ang = (2 * Math.PI * i) / Math.max(1, data.nodes.length), R = 120; const o = old[n.id];
      return { ...n, x: o ? o.x : R * Math.cos(ang) + (Math.random() - 0.5) * 40, y: o ? o.y : R * Math.sin(ang) + (Math.random() - 0.5) * 40, vx: 0, vy: 0, fx: null, fy: null }; });
    g.links = data.links || []; g.byId = {}; g.nodes.forEach((n: any) => (g.byId[n.id] = n));
    g.adj = {}; g.links.forEach((l: any) => { (g.adj[l.source] = g.adj[l.source] || new Set()).add(l.target); (g.adj[l.target] = g.adj[l.target] || new Set()).add(l.source); });
    computeComponents();
    setupCanvas();
    // honor the Settings "Graph animations" toggle: when off, settle the layout
    // synchronously once and freeze (no continuous physics), but keep redrawing
    // so pan/zoom/drag still work.
    const anim = localStorage.getItem("lm-anim") !== "off";
    g.alpha = 1;
    if (!anim) { for (let k = 0; k < 400; k++) tick(); g.alpha = 0; }
    if (!g.fitOnce) { fitGraph(false); g.fitOnce = true; }
    const loop = () => { tick(); draw(); g.raf = requestAnimationFrame(loop); }; loop();

    // ---- interaction (mouse) ----
    let mode: string | null = null, last: any = null, downPos: any = null, downNode: any = null;
    const onWheel = (e: WheelEvent) => { e.preventDefault(); const r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top, f = e.deltaY < 0 ? 1.1 : 0.9;
      g.t.x = mx - (mx - g.t.x) * f; g.t.y = my - (my - g.t.y) * f; g.t.k *= f; };
    const onDown = (e: MouseEvent) => { const r = cv.getBoundingClientRect(), n = nodeAt(e.clientX - r.left, e.clientY - r.top);
      downPos = { x: e.clientX, y: e.clientY }; downNode = n;
      if (n) { g.drag = n; n.fx = n.x; n.fy = n.y; mode = "node"; g.alpha = 1; } else mode = "pan"; last = { x: e.clientX, y: e.clientY }; };
    const onMove = (e: MouseEvent) => { const r = cv.getBoundingClientRect();
      if (mode === "pan") { g.t.x += e.clientX - last.x; g.t.y += e.clientY - last.y; last = { x: e.clientX, y: e.clientY }; }
      else if (mode === "node" && g.drag) { g.drag.fx = (e.clientX - r.left - g.t.x) / g.t.k; g.drag.fy = (e.clientY - r.top - g.t.y) / g.t.k; g.alpha = Math.max(g.alpha, 0.3); }
      else { const n = nodeAt(e.clientX - r.left, e.clientY - r.top); g.hover = n ? n.id : null; cv.style.cursor = n ? "pointer" : "grab"; } };
    const onUp = (e: MouseEvent) => {
      const moved = downPos && Math.hypot(e.clientX - downPos.x, e.clientY - downPos.y) > 5;
      if (downNode && !moved) pickRef.current(downNode.id);   // click (not drag) → open detail
      if (g.drag) { g.drag.fx = null; g.drag.fy = null; } mode = null; g.drag = null; downPos = null; downNode = null;
    };
    cv.addEventListener("wheel", onWheel, { passive: false });
    cv.addEventListener("mousedown", onDown);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);

    // ---- interaction (touch) ----
    let pinch: any = null, tStart = 0, tNode: any = null, tMoved = false;
    const pinchInfo = (e: TouchEvent, r: DOMRect) => { const a = e.touches[0], b = e.touches[1];
      return { dist: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY), mx: (a.clientX + b.clientX) / 2 - r.left, my: (a.clientY + b.clientY) / 2 - r.top }; };
    const onTStart = (e: TouchEvent) => { const r = cv.getBoundingClientRect();
      if (e.touches.length === 2) { mode = "pinch"; pinch = pinchInfo(e, r); e.preventDefault(); return; }
      const t = e.touches[0], n = nodeAt(t.clientX - r.left, t.clientY - r.top);
      tStart = performance.now(); tNode = n; tMoved = false;
      if (n) { g.drag = n; n.fx = n.x; n.fy = n.y; mode = "node"; g.alpha = 1; } else mode = "pan"; last = { x: t.clientX, y: t.clientY }; e.preventDefault(); };
    const onTMove = (e: TouchEvent) => { const r = cv.getBoundingClientRect(); tMoved = true;
      if (mode === "pinch" && e.touches.length === 2) { const pi = pinchInfo(e, r), f = pi.dist / (pinch.dist || pi.dist);
        g.t.x = pi.mx - (pi.mx - g.t.x) * f; g.t.y = pi.my - (pi.my - g.t.y) * f; g.t.k *= f; pinch = pi; }
      else if (mode === "node" && g.drag && e.touches[0]) { const t = e.touches[0]; g.drag.fx = (t.clientX - r.left - g.t.x) / g.t.k; g.drag.fy = (t.clientY - r.top - g.t.y) / g.t.k; g.alpha = Math.max(g.alpha, 0.3); }
      else if (mode === "pan" && e.touches[0]) { const t = e.touches[0]; g.t.x += t.clientX - last.x; g.t.y += t.clientY - last.y; last = { x: t.clientX, y: t.clientY }; }
      e.preventDefault(); };
    const onTEnd = (e: TouchEvent) => {
      if (tNode && !tMoved && performance.now() - tStart < 400) pickRef.current(tNode.id);  // tap → open detail
      if (e.touches.length === 0) { if (g.drag) { g.drag.fx = null; g.drag.fy = null; } mode = null; g.drag = null; pinch = null; tNode = null; }
      else if (e.touches.length === 1) { mode = "pan"; last = { x: e.touches[0].clientX, y: e.touches[0].clientY }; pinch = null; } };
    cv.addEventListener("touchstart", onTStart, { passive: false });
    cv.addEventListener("touchmove", onTMove, { passive: false });
    cv.addEventListener("touchend", onTEnd);

    // re-fit on viewport resize
    let rzT: any;
    const onResize = () => { clearTimeout(rzT); rzT = setTimeout(() => { setupCanvas(); fitGraph(false); g.alpha = Math.max(g.alpha, 0.15); }, 150); };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(g.raf);
      cv.removeEventListener("wheel", onWheel); cv.removeEventListener("mousedown", onDown);
      window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp);
      cv.removeEventListener("touchstart", onTStart); cv.removeEventListener("touchmove", onTMove); cv.removeEventListener("touchend", onTEnd);
      window.removeEventListener("resize", onResize);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  return (
    <div ref={wrapRef} className="relative w-full h-full overflow-hidden rounded-[14px] border border-[var(--line)]"
      style={{ background: "var(--graph-bg)" }}>
      <canvas ref={canvasRef} className="block w-full h-full cursor-grab active:cursor-grabbing" />
    </div>
  );
});

export default GraphCanvas;
