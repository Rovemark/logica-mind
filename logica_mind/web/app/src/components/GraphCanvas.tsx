import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { forceSimulation, forceManyBody, forceLink, forceCollide, forceCenter, forceRadial, forceX, forceY } from "d3-force";
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
  // fired when the hovered node changes (id=null on leave), with canvas-local
  // coords — powers the hover preview card.
  onHover?: (id: string | null, x: number, y: number) => void;
  // ordered node ids of a path to spotlight (everything else dims) — Path mode.
  pathIds?: string[];
  // ── layout engine ──
  // "force" = organic web (default) · "orbit" = facet hubs arranged on a circle with
  // their members orbiting them (the org-map look) · "rings" = concentric tiers by
  // importance (PageRank), sliced into angular sectors per facet.
  // groupOf/groupKey pick the facet the hubs/sectors follow (usually the colour facet).
  layout?: "force" | "orbit" | "rings";
  groupKey?: string;
  groupOf?: (n: any) => string | null;
  // label drawn at the centre of the orbit layout (the photo's company node) —
  // usually the active namespace / brain name.
  centerLabel?: string;
  // pretty-printer for hub labels (e.g. dimension ids → human label, emoji prefix)
  labelOf?: (k: string) => string;
  // shift+click on a hub → "keep ONLY this group" (the view applies the facet filter)
  onGroupSolo?: (k: string) => void;
  // persistent click-spotlight: everything except this node + its direct neighbours
  // goes translucent (the "click a hub → see only who participated" interaction).
  spotlight?: string | null;
}

// Live canvas force-simulation (Obsidian-style continuous physics):
// repulsion + spring + gravity with damping + alpha cooling; reheats on
// interaction. Pan/zoom/drag with mouse AND touch (pinch-zoom). A click/tap on a
// node calls onPick(name) so the parent can show its memories + relations.
const GraphCanvas = forwardRef<GraphHandle, Props>(function GraphCanvas(
  { data, communities, colorFor, onPick, nodeTint, onHover, pathIds, layout = "force", groupKey, groupOf, spotlight, centerLabel, labelOf, onGroupSolo }, ref,
) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const commRef = useRef(communities);
  const colorRef = useRef(colorFor);
  const pickRef = useRef(onPick);
  const tintRef = useRef(nodeTint);
  const hoverCbRef = useRef(onHover);
  const pathRef = useRef(pathIds);
  const groupRef = useRef(groupOf);
  const spotRef = useRef(spotlight);
  commRef.current = communities;
  colorRef.current = colorFor;
  pickRef.current = onPick;
  tintRef.current = nodeTint;
  hoverCbRef.current = onHover;
  pathRef.current = pathIds;
  groupRef.current = groupOf;
  spotRef.current = spotlight;
  const centerRef = useRef(centerLabel);
  centerRef.current = centerLabel;
  const labelRef = useRef(labelOf);
  labelRef.current = labelOf;
  const soloRef = useRef(onGroupSolo);
  soloRef.current = onGroupSolo;

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

  // render-only props (path spotlight, tint/highlight, community colouring, palette)
  // don't change `data`, so the data-effect won't re-run and the idle-suspend loop
  // would skip the repaint — leaving Path mode / highlight / community recolour
  // invisible until an unrelated pan/zoom/hover. Force a one-off redraw on change.
  useEffect(() => { G.current.dirty = true; }, [pathIds, communities, nodeTint, spotlight]);

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
  function draw() {
    const g = G.current, c = g.ctx; if (!c) return; const t = g.t;
    c.clearRect(0, 0, g.W, g.H); c.save(); c.translate(t.x, t.y); c.scale(t.k, t.k);
    const hi = g.hover, nbr = hi ? (g.adj[hi] || new Set()) : null;
    // Path mode: spotlight an ordered path, dim everything else
    const pids = pathRef.current || [];
    const pathSet = pids.length ? new Set(pids) : null;
    const pathEdges = pathSet ? new Set(pids.slice(0, -1).map((x, i) => [x, pids[i + 1]].sort().join(""))) : null;
    // click-spotlight: the picked node + direct neighbours stay lit, the rest goes
    // translucent. Clicking a facet HUB (anchor disc) spotlights the whole group —
    // "clicou no canal → só quem participou acende".
    const spot = spotRef.current as string | null;
    const spotN = spot && g.byId[spot] ? g.byId[spot] : null;
    const gSpot: string | null = !spotN && g.groupSpot && g.anchors && g.anchors[g.groupSpot] ? g.groupSpot : null;
    const spotSet = spotN
      ? new Set<string>([spot as string, ...((g.adj[spot as string] || new Set()) as Set<string>)])
      : gSpot ? new Set<string>(g.nodes.filter((n: any) => n._g === gSpot).map((n: any) => n.id)) : null;
    // theme-aware ink so labels/edges read on both the light and dark canvas
    const light = document.documentElement.getAttribute("data-theme") === "light";
    const edgeDead = light ? "rgba(120,130,150,.35)" : "rgba(90,100,120,.28)";
    const labelFill = light ? "#1f2940" : "#e8eef7", labelFillDim = light ? "#8a93a6" : "#5a6477";
    const labelStroke = light ? "rgba(255,255,255,.9)" : "#0a0d14";
    const edgeLabel = light ? "rgba(70,82,110,.7)" : "rgba(150,165,190,.65)";
    const nodeRing = (shared: boolean) => shared ? (light ? "rgba(60,80,160,.55)" : "rgba(255,255,255,.55)")
                                                 : (light ? "rgba(40,55,90,.3)" : "rgba(10,13,20,.9)");
    // facet hub discs + labels (orbit/rings layouts) — drawn UNDER everything so the
    // graph reads like the org-map: each facet value is a visible "department".
    if (g.anchors) {
      // centre node (the photo's company disc) — orbit layout only
      if (g.layoutMode === "orbit" && centerRef.current) {
        c.beginPath(); c.arc(0, 0, 34, 0, 6.283);
        c.fillStyle = light ? "rgba(30,40,70,.9)" : "rgba(232,238,247,.92)"; c.fill();
        c.fillStyle = light ? "#f4f7fb" : "#0a0d14"; c.font = `700 ${15 / Math.max(t.k, 0.5)}px -apple-system,sans-serif`; c.textAlign = "center"; c.textBaseline = "middle";
        const cl = String(centerRef.current); c.fillText(cl.length > 10 ? cl.slice(0, 9) + "…" : cl, 0, 0);
        c.textBaseline = "alphabetic";
      }
      for (const k in g.anchors) {
        const a = g.anchors[k]; if (k === "—") continue;
        if (g.groupSpot === k) {   // selected hub keeps a bright ring
          c.beginPath(); c.arc(a.x, a.y, (a.disc || 20) + 6, 0, 6.283);
          c.lineWidth = 2.4 / t.k; c.strokeStyle = "rgba(124,156,255,.9)"; c.stroke();
        }
        const col = a.ref ? nodeColor(a.ref) : "#7c9cff";
        // hubs keep a MINIMUM on-screen size: zoomed way out, the members fade into
        // dots but the facet hubs stay readable — the "collapse to hubs" overview.
        const dr = a.disc ? Math.max(a.disc, 20 / t.k) : 0;
        if (dr) {
          c.beginPath(); c.arc(a.x, a.y, dr, 0, 6.283);
          c.fillStyle = col + (t.k < 0.45 ? "26" : "12"); c.fill();
          c.lineWidth = 1 / t.k; c.strokeStyle = col + "2e"; c.stroke();
        }
        c.font = `600 ${13 / t.k}px -apple-system,sans-serif`; c.textAlign = "center";
        c.lineWidth = 3 / t.k; c.strokeStyle = labelStroke; c.fillStyle = col;
        const ly = a.y - (dr ? dr + 8 / t.k : 0);
        const txt = `${labelRef.current ? labelRef.current(k) : k} · ${a.count}`;
        c.strokeText(txt, a.x, ly); c.fillText(txt, a.x, ly);
      }
    }
    // LOD renderer: for a BIG graph (or while the sim is HOT / panning) draw a cheap
    // frame — every edge in ONE batched path, nodes as plain dots, labels only where
    // they're readable. This is what keeps THOUSANDS of nodes smooth on the 2D canvas;
    // the full per-edge grammar (arrows, dashes, per-edge labels) is reserved for small
    // graphs where you can actually see it. (Obsidian likewise drops detail at scale.)
    const big = g.nodes.length > 1200;
    if (g.moving || big) {
      // edges grouped BY COLOUR — a handful of strokes (one per edge type/predicate
      // class), not one per edge, so the batched draw stays cheap yet keeps the
      // colourful edge grammar at scale (greying everything was the "sem cores" bug).
      c.lineWidth = 0.9 / Math.sqrt(t.k);
      const _grp: Record<string, any[]> = {};
      g.links.forEach((l: any) => { const A = g.byId[l.source], B = g.byId[l.target]; if (!A || !B) return;
        const kind = l.kind || "relation";
        const rgb = l.valid === false ? "_d"
          : kind === "co_mention" ? COMENTION_RGB
          : kind === "semantic" ? SEMANTIC_RGB
          : kind === "suggested" ? "251,191,36"
          : (PCLASS_RGB[l.pclass || "other"] || PCLASS_RGB.other);
        (_grp[rgb] = _grp[rgb] || []).push(A, B); });
      for (const rgb in _grp) {
        c.strokeStyle = rgb === "_d" ? edgeDead : `rgba(${rgb},0.55)`;
        c.beginPath(); const arr = _grp[rgb];
        for (let i = 0; i < arr.length; i += 2) { c.moveTo(arr[i].x, arr[i].y); c.lineTo(arr[i + 1].x, arr[i + 1].y); }
        c.stroke();
      }
      g.nodes.forEach((n: any) => { const r = baseRad(n, false) / Math.sqrt(t.k);
        c.beginPath(); c.arc(n.x, n.y, r, 0, 6.283); c.fillStyle = nodeColor(n); c.fill(); });
      // settled big graph: labels only when zoomed in enough to read them, and only for
      // nodes inside the viewport (culled) so it stays cheap at thousands of nodes.
      if (!g.moving && t.k > 0.8) {
        const mnx = -t.x / t.k, mny = -t.y / t.k, mxx = (g.W - t.x) / t.k, mxy = (g.H - t.y) / t.k;
        c.fillStyle = labelFill; c.font = `${11 / t.k}px -apple-system,sans-serif`; c.textAlign = "center";
        c.lineWidth = 3 / t.k; c.strokeStyle = labelStroke;
        g.nodes.forEach((n: any) => { if (n.x < mnx || n.x > mxx || n.y < mny || n.y > mxy) return;
          const ly = n.y - (baseRad(n, n.id === hi) + 5) / t.k; c.strokeText(n.id, n.x, ly); c.fillText(n.id, n.x, ly); });
      }
      // hover overlay (works in every mode): the hovered node + its direct edges +
      // labels for it and its neighbours, so hovering always tells you what it is.
      if (hi && g.byId[hi]) { const H = g.byId[hi], nb = g.adj[hi] || new Set();
        c.strokeStyle = light ? "rgba(40,55,90,.75)" : "rgba(255,255,255,.65)"; c.lineWidth = 1.6 / Math.sqrt(t.k); c.beginPath();
        nb.forEach((id: string) => { const B = g.byId[id]; if (B) { c.moveTo(H.x, H.y); c.lineTo(B.x, B.y); } }); c.stroke();
        c.beginPath(); c.arc(H.x, H.y, (baseRad(H, true) + 2) / Math.sqrt(t.k), 0, 6.283); c.fillStyle = nodeColor(H); c.fill();
        c.fillStyle = labelFill; c.font = `${11 / t.k}px -apple-system,sans-serif`; c.textAlign = "center"; c.lineWidth = 3 / t.k; c.strokeStyle = labelStroke;
        const lab = (n: any) => { const ly = n.y - (baseRad(n, n.id === hi) + 5) / t.k; c.strokeText(n.id, n.x, ly); c.fillText(n.id, n.x, ly); };
        lab(H); nb.forEach((id: string) => { const B = g.byId[id]; if (B) lab(B); }); }
      // click-spotlight in the batched path: a translucent veil over everything, then
      // the picked node's subgraph redrawn ON TOP — others stay visible but ghosted.
      if (spotN || gSpot) {
        c.restore();
        c.fillStyle = light ? "rgba(244,247,251,0.82)" : "rgba(9,12,18,0.82)";
        c.fillRect(0, 0, g.W, g.H);
        c.save(); c.translate(t.x, t.y); c.scale(t.k, t.k);
        const members: any[] = spotN
          ? [spotN, ...Array.from((g.adj[spot as string] || new Set()) as Set<string>).map((id) => g.byId[id]).filter(Boolean)]
          : g.nodes.filter((n: any) => n._g === gSpot);
        c.strokeStyle = light ? "rgba(40,55,90,.6)" : "rgba(220,230,250,.5)"; c.lineWidth = 1.3 / Math.sqrt(t.k); c.beginPath();
        if (spotN) {
          members.forEach((B: any) => { if (B !== spotN) { c.moveTo(spotN.x, spotN.y); c.lineTo(B.x, B.y); } });
        } else if (spotSet) {                              // hub spotlight: intra-group edges
          g.links.forEach((l: any) => { if (spotSet.has(l.source) && spotSet.has(l.target)) {
            const A = g.byId[l.source], B = g.byId[l.target]; if (A && B) { c.moveTo(A.x, A.y); c.lineTo(B.x, B.y); } } });
        }
        c.stroke();
        const dot = (n: any, ring = false) => { c.beginPath(); c.arc(n.x, n.y, (baseRad(n, ring) + (ring ? 2 : 0)) / Math.sqrt(t.k), 0, 6.283); c.fillStyle = nodeColor(n); c.fill(); };
        members.forEach((B: any) => dot(B, spotN ? B === spotN : false));
        c.fillStyle = labelFill; c.font = `${11 / t.k}px -apple-system,sans-serif`; c.textAlign = "center"; c.lineWidth = 3 / t.k; c.strokeStyle = labelStroke;
        const lab2 = (n: any) => { const ly = n.y - (baseRad(n, false) + 5) / t.k; c.strokeText(n.id, n.x, ly); c.fillText(n.id, n.x, ly); };
        members.slice(0, 80).forEach((B: any) => lab2(B));   // cap labels so a huge group stays readable
      }
      c.restore(); return;
    }
    g.links.forEach((l: any) => { const A = g.byId[l.source], B = g.byId[l.target]; if (!A || !B) return;
      const active = !hi || l.source === hi || l.target === hi;
      const onPath = pathEdges ? pathEdges.has([l.source, l.target].sort().join("")) : false;
      const kind = l.kind || "relation";
      const mx = (A.x + B.x) / 2, my = (A.y + B.y) / 2 - Math.hypot(B.x - A.x, B.y - A.y) * 0.07;
      c.beginPath(); c.moveTo(A.x, A.y); c.quadraticCurveTo(mx, my, B.x, B.y);
      let rgb: string, alpha: number, width: number, dash: number[] | null = null, arrow = false;
      if (kind === "co_mention") {
        rgb = COMENTION_RGB; alpha = active ? 0.5 : 0.16; dash = [4, 4];
        width = 0.7 + Math.min(l.weight || 1, 5) * 0.26;
      } else if (kind === "semantic") {
        rgb = SEMANTIC_RGB; alpha = active ? 0.45 : 0.13; width = 0.8; dash = [1.2, 4];
      } else if (kind === "suggested") {                  // predicted-but-missing edge
        rgb = "251,191,36"; alpha = active ? 0.55 : 0.18; width = 1; dash = [2, 5];
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
      if (spotSet) {                                       // click-spotlight WINS over path
        // (an explicit click is fresher intent than a lingering path query)
        const lit = spotN ? (l.source === spot || l.target === spot)
                          : (spotSet.has(l.source) && spotSet.has(l.target));
        if (lit) { alpha = Math.max(alpha, 0.8); width = Math.max(width, 1.5); }
        else { alpha *= 0.06; arrow = false; }
      } else if (pathSet) {                                // Path-mode spotlight
        if (onPath) { rgb = "251,191,36"; alpha = 0.95; width = Math.max(width, 2.6); }
        else { alpha *= 0.1; arrow = false; }
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
    g.nodes.forEach((n: any) => { const onP = pathSet ? pathSet.has(n.id) : null;
      const inS = spotSet ? spotSet.has(n.id) : null;
      // spotlight wins over path (explicit click beats a lingering path query)
      const dimmed = spotSet ? inS === false : onP === false;
      const active = (!hi || n.id === hi || (nbr && nbr.has(n.id))) && !dimmed;
      const dim = dimmed;
      const col = nodeColor(n), rad = baseRad(n, n.id === hi);
      if (n.id === hi || (nbr && nbr.has(n.id))) { c.beginPath(); c.arc(n.x, n.y, rad + 7 / t.k, 0, 6.283); c.fillStyle = col + "33"; c.fill(); }
      c.beginPath(); c.arc(n.x, n.y, rad / Math.sqrt(t.k), 0, 6.283);
      c.fillStyle = dim ? col + "1f" : (active ? col : col + "44"); c.fill();
      c.lineWidth = (n.shared ? 2 : 1.4) / t.k; c.strokeStyle = nodeRing(!!n.shared); c.stroke();
      if (onP) { c.beginPath(); c.arc(n.x, n.y, (rad + 3) / Math.sqrt(t.k), 0, 6.283); c.lineWidth = 2.4 / t.k; c.strokeStyle = "rgba(251,191,36,.95)"; c.stroke(); }
      else if (spotSet && n.id === spot) { c.beginPath(); c.arc(n.x, n.y, (rad + 3) / Math.sqrt(t.k), 0, 6.283); c.lineWidth = 2.2 / t.k; c.strokeStyle = "rgba(124,156,255,.95)"; c.stroke(); }
      else if (n.bridge && !dim) { c.beginPath(); c.arc(n.x, n.y, (rad + 2.5) / Math.sqrt(t.k), 0, 6.283); c.lineWidth = 1.4 / t.k; c.setLineDash([2 / t.k, 2 / t.k]); c.strokeStyle = "rgba(245,158,11,.85)"; c.stroke(); c.setLineDash([]); }
      if (t.k > 0.6 && (active || onP)) { c.fillStyle = active || onP ? labelFill : labelFillDim; c.font = `${11 / t.k}px -apple-system,sans-serif`; c.textAlign = "center";
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
  // facet hub (anchor disc) under the cursor — hubs are CLICKABLE: clicking one
  // spotlights its whole group ("clicou no canal → só quem participou acende").
  function anchorAt(cx: number, cy: number): string | null {
    const g = G.current; if (!g.anchors) return null;
    const x = (cx - g.t.x) / g.t.k, y = (cy - g.t.y) / g.t.k;
    for (const k in g.anchors) { const a = g.anchors[k];
      // hit-radius mirrors the drawn min-screen-size disc (zoomed out, hubs stay clickable)
      const dr = a.disc ? Math.max(a.disc, 20 / g.t.k) : 0;
      if (k !== "—" && dr && Math.hypot(a.x - x, a.y - y) <= dr) return k; }
    return null;
  }

  // (re)build the simulation whenever the graph data changes
  useEffect(() => {
    const g = G.current, cv = canvasRef.current; if (!cv) return;
    if (g.raf) cancelAnimationFrame(g.raf);
    const old: Record<string, any> = {}; (g.nodes || []).forEach((n: any) => (old[n.id] = { x: n.x, y: n.y, vx: n.vx, vy: n.vy, core: n._core }));
    g.nodes = (data.nodes || []).map((n) => { const o = old[n.id];
      return { ...n, x: o ? o.x : 0, y: o ? o.y : 0, vx: 0, vy: 0, fx: null, fy: null, _new: !o }; });
    g.links = data.links || []; g.byId = {}; g.nodes.forEach((n: any) => (g.byId[n.id] = n));
    g.adj = {}; g.links.forEach((l: any) => { (g.adj[l.source] = g.adj[l.source] || new Set()).add(l.target); (g.adj[l.target] = g.adj[l.target] || new Set()).add(l.source); });
    computeComponents();
    // Identify the CORE — the DOMINANT connected component. The layout pulls the core
    // to the centre and pushes fragments/orphans to an OUTER RING → Obsidian's centred
    // globe (verified headless). If no component dominates (all tiny pairs / all
    // orphans) there is NO core: everyone shares one centred cloud, so we never strand
    // a lonely dot in the middle of a giant empty ring.
    const _sz: Record<number, number> = {};
    g.nodes.forEach((n: any) => (_sz[g.comp[n.id]] = (_sz[g.comp[n.id]] || 0) + 1));
    let _gi = -1, _gz = 0; for (const k in _sz) if (_sz[+k] > _gz) { _gz = _sz[+k]; _gi = +k; }
    const _coreOk = _gz >= Math.max(8, g.nodes.length * 0.12);   // needs a real giant to ring around
    let _ringN = 0; g.nodes.forEach((n: any) => { n._core = _coreOk ? g.comp[n.id] === _gi : true; if (!n._core) _ringN++; });
    // ring radius scales with how many nodes sit on it, so they spread along the
    // circumference instead of piling into a thick crowded band.
    g.ringR = _ringN ? Math.min(2400, Math.max(1100, Math.round(_ringN * 3.2))) : 0;
    // ── layout targets (orbit / rings) ──────────────────────────────────────────
    // The alternative layouts are TARGET-driven: every node gets a (_tx,_ty) and a
    // gentle forceX/forceY pulls it there — so switching layouts MORPHS the graph
    // smoothly instead of teleporting it. "orbit" = facet hubs on a circle, members
    // spiralling around their hub (golden angle, best-connected innermost — the
    // org-map look). "rings" = concentric tiers by PageRank importance (hubs in the
    // middle, periphery outside), sliced into one angular sector per facet value.
    const layoutMode = layout || "force";
    g.layoutMode = layoutMode; g.anchors = null; g.groupSpot = null;
    if (layoutMode !== "force") {
      const gidOf = (n: any) => (groupKey === "community")
        ? "C" + (g.comp[n.id] ?? 0)
        : ((groupRef.current && groupRef.current(n)) || "—");
      const groups: Record<string, any[]> = {};
      g.nodes.forEach((n: any) => { const k = gidOf(n); n._g = k; (groups[k] = groups[k] || []).push(n); });
      const names = Object.keys(groups).sort((a, b) => groups[b].length - groups[a].length);
      const N = g.nodes.length;
      g.anchors = {};
      if (layoutMode === "orbit") {
        // the photo look: facet hubs (channels/agents/types…) on an inner circle with
        // their participants orbiting them; facet-LESS nodes form the outer rim arcs.
        const real = names.filter((k) => k !== "—");
        const periph = groups["—"] || [];
        // hub-ring radius also scales with the BIGGEST group's own spiral radius —
        // otherwise a dominant group (e.g. telegram with 130 members) overlaps the
        // centre and its neighbours instead of reading as a clean orbit.
        const maxGroup = real.length ? Math.max(...real.map((k) => groups[k].length)) : 0;
        const R1 = real.length <= 1 ? 0 : Math.max(
          340,
          Math.round(Math.sqrt(N) * 30 + real.length * 26),
          Math.round(30 * Math.sqrt(maxGroup) * 1.7),
        );
        real.forEach((k, gi) => {
          const ang = (2 * Math.PI * gi) / Math.max(1, real.length) - Math.PI / 2;
          const ax = R1 * Math.cos(ang), ay = R1 * Math.sin(ang);
          const members = groups[k].slice().sort((a, b) => (b.degree || 0) - (a.degree || 0));
          members.forEach((n: any, j: number) => { const r = 30 * Math.sqrt(j + 0.5), th = j * 2.39996;
            n._tx = ax + r * Math.cos(th); n._ty = ay + r * Math.sin(th); });
          // tiny hubs keep a small disc — a 1-member hub with the full-size disc
          // swallowed its own node
          g.anchors[k] = { x: ax, y: ay, count: groups[k].length, ref: members[0],
            disc: groups[k].length < 2 ? 14 : 26 + Math.sqrt(groups[k].length) * 9 };
        });
        if (periph.length) {
          // periphery on MULTIPLE concentric rims (~140/rim): one giant circle for a
          // facet-poor dataset (80% of nodes) dwarfed the hubs and wasted the canvas
          const rims = Math.max(1, Math.ceil(periph.length / 140));
          const perRim = Math.ceil(periph.length / rims);
          const RP0 = Math.max(R1 * 1.45, 520);
          periph.forEach((n: any, j: number) => {
            const rim = Math.floor(j / perRim), idx = j % perRim, cnt = Math.min(perRim, periph.length - rim * perRim);
            const a = (2 * Math.PI * idx) / Math.max(1, cnt) - Math.PI / 2 + rim * 0.11;
            const RP = RP0 + rim * 90;
            n._tx = RP * Math.cos(a); n._ty = RP * Math.sin(a);
          });
        }
      } else {
        const order = g.nodes.slice().sort((a: any, b: any) => (b.centrality || 0) - (a.centrality || 0));
        const tier: Record<string, number> = {};
        order.forEach((n: any, i: number) => { const q = i / Math.max(1, order.length);
          tier[n.id] = q < 0.06 ? 0 : q < 0.30 ? 1 : q < 0.65 ? 2 : 3; });
        const SC = Math.max(1, Math.sqrt(N / 260));
        const tierR = [70 * SC, 300 * SC, 560 * SC, 820 * SC];
        let acc = 0;
        names.forEach((k) => {
          const frac = groups[k].length / N, a0 = acc * 2 * Math.PI - Math.PI / 2, a1 = (acc + frac) * 2 * Math.PI - Math.PI / 2; acc += frac;
          groups[k].forEach((n: any, j: number) => { const a = a0 + ((j + 0.5) / groups[k].length) * (a1 - a0);
            const R = tierR[tier[n.id]]; n._tx = R * Math.cos(a); n._ty = R * Math.sin(a); });
          const mid = (a0 + a1) / 2, LR = tierR[3] + 120;
          g.anchors[k] = { x: LR * Math.cos(mid), y: LR * Math.sin(mid), count: groups[k].length, ref: groups[k][0], disc: 0 };
        });
      }
    }
    g.nodes.forEach((n: any, i: number) => {
      if (layoutMode !== "force") {
        // seed NEW nodes right at their layout target; reused nodes keep their spot
        // and MORPH there via the target forces (smooth layout transition).
        if (n._new) { n.x = (n._tx || 0) + (Math.random() - 0.5) * 30; n.y = (n._ty || 0) + (Math.random() - 0.5) * 30; }
        return;
      }
      // seed NEW nodes by role; also RESEED a reused node whose core membership FLIPPED
      // (toggle/layer change) so forceRadial doesn't fling it across the whole canvas.
      const flip = !n._new && old[n.id] && old[n.id].core !== undefined && old[n.id].core !== n._core;
      if (n._new || flip) { const ang = (2 * Math.PI * i) / Math.max(1, g.nodes.length), R = n._core ? 150 : (g.ringR || 760);
        n.x = R * Math.cos(ang) + (Math.random() - 0.5) * 40; n.y = R * Math.sin(ang) + (Math.random() - 0.5) * 40; } });
    setupCanvas();
    // d3-force layout — the proven, stable force engine (Barnes-Hut O(N log N)) that
    // graph apps like Obsidian rely on. Replaces the hand-rolled physics that kept
    // imploding / exploding / vanishing. Nodes are shared (d3 moves them in place);
    // forceLink gets a throwaway copy so g.links keeps string ids for rendering.
    // forceCenter + forceRadial give the centred globe (core in, fragments ringed).
    if (g.sim) g.sim.stop();
    // dense graphs (avg degree ~14 here) collapse into an invisible hairball if
    // EVERY link pulls with the same strength — so we keep d3's DEFAULT link
    // strength (1/min(deg)), which auto-weakens springs on high-degree hubs. That
    // degree-normalization is exactly how Obsidian-style graphs stay spread. A
    // strong, long-range charge opens the cluster; a roomy link distance gives it
    // air; a gentle x/y pull keeps it centered without crushing it back to a ball.
    // BIG graphs use a faster physics profile (higher Barnes-Hut theta, shorter charge
    // range, faster cooling, no collide) so a few thousand nodes settle in a few
    // seconds at a watchable framerate instead of crawling; small graphs keep the
    // higher-quality profile (collide → no overlap, slower cooling → tighter layout).
    const bigG = g.nodes.length > 1200;
    if (layoutMode === "force") {
      g.sim = forceSimulation(g.nodes)
        .force("charge", forceManyBody().strength(bigG ? -260 : -220).distanceMax(bigG ? 650 : 1000).theta(bigG ? 1.5 : 0.85))
        .force("link", forceLink(g.links.map((l: any) => ({ source: l.source, target: l.target })))
                         .id((d: any) => d.id).distance(38))
        // forceCenter locks the centre of mass at the origin (no drift / off-centre
        // clumping); forceRadial pulls the connected CORE to the centre (radius 0) and
        // pushes fragments/orphans out to a ring → the Obsidian centred globe.
        .force("center", forceCenter(0, 0))
        .force("radial", forceRadial((d: any) => (d._core ? 0 : g.ringR), 0, 0).strength((d: any) => (d._core ? 0.12 : 0.30)))
        .alphaDecay(bigG ? 0.06 : 0.03)
        .velocityDecay(bigG ? 0.5 : 0.42)
        .stop();
      if (!bigG) g.sim.force("collide", forceCollide().radius((d: any) => baseRad(d, false) + 5));
    } else {
      // target-driven layouts (orbit/rings): the STRUCTURE comes from the (_tx,_ty)
      // targets, not from the springs — so links are weak, charge is short-range
      // breathing room, and a firm x/y pull holds the constellation shape.
      g.sim = forceSimulation(g.nodes)
        .force("charge", forceManyBody().strength(-50).distanceMax(260).theta(1.2))
        .force("link", forceLink(g.links.map((l: any) => ({ source: l.source, target: l.target })))
                         .id((d: any) => d.id).distance(34).strength(0.03))
        .force("tx", forceX((d: any) => d._tx || 0).strength(0.22))
        .force("ty", forceY((d: any) => d._ty || 0).strength(0.22))
        .alphaDecay(0.05)
        .velocityDecay(0.5)
        .stop();
      if (g.nodes.length <= 2500) g.sim.force("collide", forceCollide().radius((d: any) => baseRad(d, false) + 4));
    }
    // brief synchronous pre-settle so the first paint is organized — BOUNDED by node
    // count so a large graph doesn't freeze the main thread on load (~constant cap);
    // the rAF loop animates the rest of the settle, re-fitting as the cluster grows.
    const pre = Math.max(8, Math.min(50, Math.round(40000 / Math.max(1, g.nodes.length))));
    const _t0 = performance.now();
    for (let k = 0; k < pre && performance.now() - _t0 < 90; k++) g.sim.tick();  // hard 90ms cap → never a load freeze
    fitGraph(false);
    g.alpha = 0; g.fitted = false; g.initialSettle = true; g.fc = 0;
    // loop: relay reheat/drag (g.alpha) into the sim, tick d3 while hot, frame once
    // settled, always redraw (so hover/pan/zoom/drag stay live).
    g.dirty = true;
    const loop = () => {
      if (g.sim) {
        if (g.alpha > 0) { g.sim.alpha(Math.max(g.sim.alpha(), g.alpha)); g.alpha = 0; g.fitted = false; g.dirty = true; }
        if (g.sim.alpha() > g.sim.alphaMin()) { g.sim.tick(); g.hot = true;
          // keep the growing cluster framed during the FIRST settle only (never yank
          // the camera mid-drag or after the user has panned/zoomed).
          if (g.initialSettle && !g.drag && !g.pan && (g.fc = (g.fc || 0) + 1) % 15 === 0) fitGraph(false); }
        else { if (!g.fitted) { g.fitted = true; fitGraph(true); g.dirty = true; } g.hot = false; g.initialSettle = false; }
      }
      // cheap batched draw while physics is hot OR panning (a cheap hover overlay in
      // the batched path still gives hover feedback mid-settle, no rich-draw cost).
      g.moving = g.hot || g.pan;
      // idle-suspend: only repaint when the view actually changed. The signature
      // catches pan/zoom/fit/hover automatically (they move g.t or g.hover) with no
      // per-handler bookkeeping; g.hot covers the live settle; g.dirty forces a
      // one-off rich repaint (render-prop change, pan/drag release). theme is in the
      // sig so an OS dark/light flip repaints. When idle → draw() never runs, so a
      // 1000-node graph sits at ~0% CPU instead of repainting 60x/second.
      const _light = document.documentElement.getAttribute("data-theme") === "light" ? 1 : 0;
      const sig = `${g.t.x | 0},${g.t.y | 0},${g.t.k.toFixed(3)},${g.hover},${g.moving ? 1 : 0},${_light},${g.groupSpot || ""}`;
      if (g.hot || g.dirty || sig !== g.lastSig) { draw(); g.lastSig = sig; g.dirty = false; }
      g.raf = requestAnimationFrame(loop);
    }; loop();

    // ---- interaction (mouse) ----
    let mode: string | null = null, last: any = null, downPos: any = null, downNode: any = null;
    const onWheel = (e: WheelEvent) => { e.preventDefault(); g.initialSettle = false; const r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top, f = e.deltaY < 0 ? 1.1 : 0.9;
      g.t.x = mx - (mx - g.t.x) * f; g.t.y = my - (my - g.t.y) * f; g.t.k *= f; };
    const onDown = (e: MouseEvent) => { g.initialSettle = false; const r = cv.getBoundingClientRect(), n = nodeAt(e.clientX - r.left, e.clientY - r.top);
      downPos = { x: e.clientX, y: e.clientY }; downNode = n;
      if (n) { g.drag = n; n.fx = n.x; n.fy = n.y; mode = "node"; g.alpha = 1; } else { mode = "pan"; g.pan = true; } last = { x: e.clientX, y: e.clientY }; };
    const onMove = (e: MouseEvent) => { const r = cv.getBoundingClientRect();
      if (mode === "pan") { g.t.x += e.clientX - last.x; g.t.y += e.clientY - last.y; last = { x: e.clientX, y: e.clientY }; }
      else if (mode === "node" && g.drag) { g.drag.fx = (e.clientX - r.left - g.t.x) / g.t.k; g.drag.fy = (e.clientY - r.top - g.t.y) / g.t.k; g.alpha = Math.max(g.alpha, 0.3); }
      else { const n = nodeAt(e.clientX - r.left, e.clientY - r.top); const id = n ? n.id : null;
        if (id !== g.hover) { g.hover = id; hoverCbRef.current?.(id, e.clientX - r.left, e.clientY - r.top); }
        cv.style.cursor = n || anchorAt(e.clientX - r.left, e.clientY - r.top) ? "pointer" : "grab"; } };
    const onLeave = () => { if (g.hover) { g.hover = null; hoverCbRef.current?.(null, 0, 0); } };
    cv.addEventListener("mouseleave", onLeave);
    const onUp = (e: MouseEvent) => {
      const moved = downPos && Math.hypot(e.clientX - downPos.x, e.clientY - downPos.y) > 5;
      const wasPan = !downNode;
      if (downNode && !moved) pickRef.current(downNode.id);   // click (not drag) → open detail
      if (!downNode && !moved) {                              // click on a hub → group spotlight; empty space clears it
        const r2 = cv.getBoundingClientRect(), ak = anchorAt(e.clientX - r2.left, e.clientY - r2.top);
        if (ak && e.shiftKey && soloRef.current) {            // shift+click → keep ONLY this group (facet filter)
          soloRef.current(ak); g.groupSpot = null; g.dirty = true;
        } else {
          const next = ak ? (g.groupSpot === ak ? null : ak) : null;
          if (next !== g.groupSpot) { g.groupSpot = next; g.dirty = true; }
        }
      }
      if (g.drag) { g.drag.fx = null; g.drag.fy = null; } mode = null; g.drag = null; downPos = null; downNode = null;
      g.pan = false; g.dirty = true;   // end pan/drag → one rich repaint
      // after a PAN only (not a node drag), the graph slid under a now-stale g.hover →
      // re-evaluate at the release point so the highlight matches the cursor.
      if (moved && wasPan) { const r = cv.getBoundingClientRect(), n2 = nodeAt(e.clientX - r.left, e.clientY - r.top), id2 = n2 ? n2.id : null;
        if (id2 !== g.hover) { g.hover = id2; hoverCbRef.current?.(id2, e.clientX - r.left, e.clientY - r.top); } }
    };
    cv.addEventListener("wheel", onWheel, { passive: false });
    cv.addEventListener("mousedown", onDown);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);

    // ---- interaction (touch) ----
    let pinch: any = null, tStart = 0, tNode: any = null, tMoved = false;
    const pinchInfo = (e: TouchEvent, r: DOMRect) => { const a = e.touches[0], b = e.touches[1];
      return { dist: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY), mx: (a.clientX + b.clientX) / 2 - r.left, my: (a.clientY + b.clientY) / 2 - r.top }; };
    const onTStart = (e: TouchEvent) => { g.initialSettle = false; const r = cv.getBoundingClientRect();
      if (e.touches.length === 2) { mode = "pinch"; g.pan = true; pinch = pinchInfo(e, r); e.preventDefault(); return; }
      const t = e.touches[0], n = nodeAt(t.clientX - r.left, t.clientY - r.top);
      tStart = performance.now(); tNode = n; tMoved = false;
      if (n) { g.drag = n; n.fx = n.x; n.fy = n.y; mode = "node"; g.alpha = 1; } else { mode = "pan"; g.pan = true; } last = { x: t.clientX, y: t.clientY }; e.preventDefault(); };
    const onTMove = (e: TouchEvent) => { const r = cv.getBoundingClientRect(); tMoved = true;
      if (mode === "pinch" && e.touches.length === 2) { const pi = pinchInfo(e, r), f = pi.dist / (pinch.dist || pi.dist);
        g.t.x = pi.mx - (pi.mx - g.t.x) * f; g.t.y = pi.my - (pi.my - g.t.y) * f; g.t.k *= f; pinch = pi; }
      else if (mode === "node" && g.drag && e.touches[0]) { const t = e.touches[0]; g.drag.fx = (t.clientX - r.left - g.t.x) / g.t.k; g.drag.fy = (t.clientY - r.top - g.t.y) / g.t.k; g.alpha = Math.max(g.alpha, 0.3); }
      else if (mode === "pan" && e.touches[0]) { const t = e.touches[0]; g.t.x += t.clientX - last.x; g.t.y += t.clientY - last.y; last = { x: t.clientX, y: t.clientY }; }
      e.preventDefault(); };
    const onTEnd = (e: TouchEvent) => {
      if (tNode && !tMoved && performance.now() - tStart < 400) pickRef.current(tNode.id);  // tap → open detail
      if (e.touches.length === 0) { if (g.drag) { g.drag.fx = null; g.drag.fy = null; } mode = null; g.drag = null; pinch = null; tNode = null; g.pan = false; g.dirty = true; }
      else if (e.touches.length === 1) { mode = "pan"; g.pan = true; last = { x: e.touches[0].clientX, y: e.touches[0].clientY }; pinch = null; } };
    cv.addEventListener("touchstart", onTStart, { passive: false });
    cv.addEventListener("touchmove", onTMove, { passive: false });
    cv.addEventListener("touchend", onTEnd);

    // re-fit on viewport resize
    let rzT: any;
    const onResize = () => { clearTimeout(rzT); rzT = setTimeout(() => { setupCanvas(); fitGraph(false); g.alpha = Math.max(g.alpha, 0.15); }, 150); };
    window.addEventListener("resize", onResize);

    // Escape clears the hub spotlight (the view clears its own filters on Escape too)
    const onKeyEsc = (e: KeyboardEvent) => { if (e.key === "Escape" && g.groupSpot) { g.groupSpot = null; g.dirty = true; } };
    window.addEventListener("keydown", onKeyEsc);

    return () => {
      cancelAnimationFrame(g.raf);
      window.removeEventListener("keydown", onKeyEsc);
      cv.removeEventListener("wheel", onWheel); cv.removeEventListener("mousedown", onDown);
      cv.removeEventListener("mouseleave", onLeave);
      window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp);
      cv.removeEventListener("touchstart", onTStart); cv.removeEventListener("touchmove", onTMove); cv.removeEventListener("touchend", onTEnd);
      window.removeEventListener("resize", onResize);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, layout, groupKey]);

  return (
    <div ref={wrapRef} className="relative w-full h-full overflow-hidden rounded-[14px] border border-[var(--line)]"
      style={{ background: "var(--graph-bg)" }}>
      <canvas ref={canvasRef} className="block w-full h-full cursor-grab active:cursor-grabbing" />
    </div>
  );
});

export default GraphCanvas;
