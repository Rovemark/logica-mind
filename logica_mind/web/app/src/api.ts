// Tiny typed client for the Python JSON API (same-origin; dev proxies /api).

export type Layer = "episodic" | "semantic" | "graph" | "user";
export const LAYERS: Layer[] = ["episodic", "semantic", "graph", "user"];

export const PALETTE = [
  "#7c9cff", "#4ade80", "#f59e0b", "#a78bfa", "#f472b6",
  "#22d3ee", "#fb7185", "#a3e635", "#e879f9", "#38bdf8",
];

// Stable, maximally-separated colour for a distinct facet value (agent/clone,
// dimension, project, entity type…). Golden-angle hue assignment by first-seen
// order gives many well-spread hues that don't drift across renders — the
// Obsidian "colour group" look, generalised to any facet. Empty value → neutral.
const _facetHue: Record<string, number> = {};
let _facetHueN = 0;
export function valueColor(value?: string | null): string {
  if (!value) return "var(--dim2)";
  if (!(value in _facetHue)) { _facetHue[value] = (_facetHueN * 137.508) % 360; _facetHueN++; }
  return `hsl(${_facetHue[value].toFixed(1)}, 67%, 61%)`;
}

export interface Memory {
  id: string; namespace: string; content: string; layer: Layer;
  importance?: number; tags?: string[]; metadata?: Record<string, any>;
  created_at?: string; access_count?: number;
}
export interface Stats { episodic: number; semantic: number; graph: number; user: number; total: number; }
export interface NsItem { namespace: string; total: number; stats: Stats; }
export type LinkKind = "relation" | "co_mention" | "semantic" | "suggested";
export interface GraphNode { id: string; shared?: boolean; namespaces?: string[]; dimension?: string; type?: string; channel?: string; degree?: number; centrality?: number; bridge?: boolean; }
export interface GraphLink { source: string; target: string; label: string; confidence?: number; valid?: boolean; kind?: LinkKind; weight?: number; directed?: boolean; pclass?: string; }
export interface SuggestedLink { a: string; b: string; common_neighbors: number; score: number; via: string[]; }
export interface GraphData { nodes: GraphNode[]; links: GraphLink[]; namespaces?: string[]; focus?: string | null; depth?: number; }
export interface Relation { source: string; target: string; label: string; confidence?: number; valid?: boolean; valid_from?: string; valid_to?: string; }
export interface RecallHit { score: number; components?: Record<string, any>; memory: Memory; }
export interface ContextCandidate { score: number; components?: Record<string, any>; included: boolean; memory: Memory; }
export interface ContextResult { namespace: string; query: string; budget: number; tokens: number; block: string; candidates: ContextCandidate[]; }
export interface Observation { kind: "hub" | "co_occurrence"; entities: string[]; count: number; shared: string[]; text: string; namespace?: string; }
export interface AddResultItem { content: string; layer: string; op: "new" | "updated"; superseded?: string | null; category?: string | null; dimension?: string | null; }
export interface DimCategory { name: string; count: number; }
export interface DimensionEntry { id: string; label: string; group: string; maslow: string | null; count: number; categories: DimCategory[]; }
export interface DimensionsData { dimensions: DimensionEntry[]; uncategorized: number; maslow: string[]; }
export interface AddResult { ok: boolean; namespace: string; kind: string; llm: boolean; created: AddResultItem[]; graph_edges: number; user_updated: boolean; deduped: boolean; }
export interface SearchEntity { name: string; namespace: string; degree: number; type?: string; }
export interface SearchResults { memories: { score: number; memory: Memory }[]; entities: SearchEntity[]; namespaces: string[]; categories?: { name: string; count: number }[]; }
export interface IntegrationOption { id: string; label: string; model?: string; blurb?: string; env?: string | null; detected: boolean; installed: boolean; }
export interface IntegrationsData {
  active: {
    store: { id: string; backends: string[] };
    embedder: { id: string; model?: string | null; dims?: number | null };
    llm: { id: string; model?: string | null; available: boolean };
    reranker?: string | null;
  };
  available: { llm: IntegrationOption[]; embedders: IntegrationOption[]; rerankers: IntegrationOption[]; stores: IntegrationOption[] };
}
export interface DreamCadence { interval_hours: number; batch: number; auto: boolean; }
export interface DreamSummary { cycles: number; distilled: number; reinforced: number; forgotten: number; derived: number; inferred: number; graph_edges: number; ops: number; }
export interface PathHop { subject: string; predicate: string; object: string; confidence: number; }
export interface PathResult { from: string; to: string; found: boolean; path: string[]; hops: PathHop[]; }
export interface ConnEntity { name: string; degree: number; type?: string; dimension?: string | null; }
export interface ConnRelation { subject: string; predicate: string; object: string; valid: boolean; id: string; }
export interface Connections { entities: ConnEntity[]; relations: ConnRelation[]; mentions: Memory[]; siblings: Memory[]; }
export interface Community { nodes: string[]; size: number; facts: string[]; }
export interface AnalyticsLakeRow { namespace: string; total: number; entities: number; facts: number; relations: number; last: string | null; spark: number[]; }
export interface AnalyticsData {
  totals: Record<string, number>;
  timeseries: { date: string; count: number }[];
  by_source: { source: string; count: number }[];
  by_namespace: AnalyticsLakeRow[];
  ops: { requests: number; avg_latency_ms: number; error_rate: number };
}

const j = async (u: string) => {
  const r = await fetch(u);
  if (!r.ok) throw new Error(`${r.status} ${u}`);
  return r.json();
};
const nsq = (ns: string) => `namespace=${encodeURIComponent(ns)}`;

export const api = {
  namespaces: (): Promise<{ namespaces: NsItem[] }> => j(`/api/namespaces`),
  stats: (ns: string): Promise<{ namespace: string; stats: Stats }> => j(`/api/stats?${nsq(ns)}`),
  analytics: (ns: string, range = 30): Promise<AnalyticsData> => j(`/api/analytics?${nsq(ns)}&range=${range}`),
  integrations: (): Promise<IntegrationsData> => j(`/api/integrations`),
  setLLM: (id: string): Promise<{ ok: boolean; error?: string; llm?: any }> => post(`/api/integrations`, { llm: id }),
  dreamConfig: (): Promise<{ dream: DreamCadence; defaults: DreamCadence }> => j(`/api/dream/config`),
  setDreamConfig: (cfg: Partial<DreamCadence>): Promise<{ ok: boolean; dream: DreamCadence }> => post(`/api/dream/config`, cfg),
  dimensions: (ns: string): Promise<DimensionsData> => j(`/api/dimensions?${nsq(ns)}`),
  search: (q: string, limit = 6): Promise<SearchResults> => j(`/api/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  context: (ns: string, q: string, budget = 1200): Promise<ContextResult> =>
    j(`/api/context?${nsq(ns)}&q=${encodeURIComponent(q)}&budget=${budget}`),
  observations: (ns: string): Promise<{ observations: Observation[] }> => j(`/api/observations?${nsq(ns)}`),
  recall: (ns: string, q: string, limit = 15): Promise<{ query: string; results: RecallHit[] }> =>
    j(`/api/recall?${nsq(ns)}&q=${encodeURIComponent(q)}&limit=${limit}`),
  memories: (ns: string, layer?: string, dimension?: string, category?: string): Promise<{ memories: Memory[] }> =>
    j(`/api/memories?${nsq(ns)}${layer ? `&layer=${layer}` : ""}${dimension ? `&dimension=${encodeURIComponent(dimension)}` : ""}${category ? `&category=${encodeURIComponent(category)}` : ""}`),
  graph: (ns: string, history: boolean, at?: string | null,
          opts?: { layers?: string[]; focus?: string | null; depth?: number }): Promise<GraphData> =>
    j(`/api/graph?${nsq(ns)}&history=${history ? 1 : 0}${at ? `&at=${encodeURIComponent(at)}` : ""}`
      + `${opts?.layers ? `&layers=${opts.layers.join(",")}` : ""}`
      + `${opts?.focus ? `&focus=${encodeURIComponent(opts.focus)}` : ""}`
      + `${opts?.depth ? `&depth=${opts.depth}` : ""}`),
  timerange: (ns: string): Promise<{ min: string | null; max: string | null }> => j(`/api/timerange?${nsq(ns)}`),
  communities: (ns: string): Promise<{ namespace: string; communities: Community[] }> => j(`/api/communities?${nsq(ns)}`),
  reflect: (ns: string): Promise<{ namespace: string; insight: string }> => j(`/api/reflect?${nsq(ns)}`),
  user: (ns: string): Promise<{ namespace: string; profile: string }> => j(`/api/user?${nsq(ns)}`),
  calendar: (ns: string): Promise<{ days: Record<string, Stats> }> => j(`/api/calendar?${nsq(ns)}`),
  day: (ns: string, date: string): Promise<{ date: string; memories: Memory[] }> =>
    j(`/api/day?${nsq(ns)}&date=${date}`),
  node: (ns: string, name: string, preview = false): Promise<{ name: string; type: string; aliases: string[]; connected: string[]; unlinked?: { entity: string; count: number }[]; memories: Memory[] }> =>
    j(`/api/node?${nsq(ns)}&name=${encodeURIComponent(name)}${preview ? "&preview=1" : ""}`),
  // unlinked mentions are expensive (full graph scan) — fetched lazily, after the panel opens
  nodeUnlinked: (ns: string, name: string): Promise<{ unlinked: { entity: string; count: number }[] }> =>
    j(`/api/node?${nsq(ns)}&name=${encodeURIComponent(name)}&unlinked=1`),
  // rename/merge an entity: variant resolves to canonical from now on (non-destructive)
  entityAlias: (ns: string, variant: string, canonical: string): Promise<{ ok: boolean; canonical: string }> =>
    post("/api/entity/alias", { namespace: wns(ns) || ns, variant, canonical }),
  sessions: (ns: string): Promise<{ sessions: SessionItem[] }> => j(`/api/sessions?${nsq(ns)}`),
  sessionMemories: (ns: string, session: string): Promise<{ memories: Memory[] }> =>
    j(`/api/memories?${nsq(ns)}&session=${encodeURIComponent(session)}`),
  exportNs: (ns: string): Promise<{ namespace: string; count: number; memories: Memory[] }> => j(`/api/export?${nsq(ns)}`),
  provenance: (ns: string, id: string): Promise<{ memory?: Memory; from: Memory[]; supersedes?: string }> =>
    j(`/api/provenance?${nsq(ns)}&id=${encodeURIComponent(id)}`),
  connected: (ns: string, id: string): Promise<Connections> =>
    j(`/api/connected?${nsq(ns)}&id=${encodeURIComponent(id)}`),
  path: (ns: string, from: string, to: string): Promise<PathResult> =>
    j(`/api/path?${nsq(ns)}&from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`),
  suggested: (ns: string): Promise<{ suggested: SuggestedLink[] }> => j(`/api/suggested?${nsq(ns)}`),
  bridges: (ns: string): Promise<{ bridges: { entity: string; degree: number }[] }> => j(`/api/bridges?${nsq(ns)}`),
  scan: (path?: string): Promise<any> => j(`/api/scan${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  bundle: (ns: string): Promise<any> => j(`/api/bundle?${nsq(ns)}`),
  peers: (ns: string): Promise<{ peers: PeerPair[] }> => j(`/api/peers?${nsq(ns)}`),
  peerCard: (ns: string, observer: string, observed: string): Promise<{ card: string }> =>
    j(`/api/peer_card?${nsq(ns)}&observer=${encodeURIComponent(observer)}&observed=${encodeURIComponent(observed)}`),
  contradictions: (ns: string): Promise<{ contradictions: Contradiction[] }> => j(`/api/contradictions?${nsq(ns)}`),
  diff: (ns: string, since: string): Promise<{ diff: DiffItem[] }> => j(`/api/diff?${nsq(ns)}&since=${since}`),

  dreams: (ns: string, limit = 50): Promise<{ dreams: DreamReport[]; summary: DreamSummary }> =>
    j(`/api/dreams?${nsq(ns)}&limit=${limit}`),
  contested: (ns: string): Promise<{ contested: ContestedPair[] }> => j(`/api/contested?${nsq(ns)}`),
  surprises: (ns: string): Promise<{ surprises: SurpriseEvent[] }> => j(`/api/surprises?${nsq(ns)}`),
  forgetCurve: (ns: string): Promise<{ curve: ForgetCurveEntry[] }> => j(`/api/forget_curve?${nsq(ns)}`),
  forgetAbout: (ns: string, entity: string) => post("/api/forget_about", { namespace: wns(ns) || ns, entity }),
  staleBeliefs: (ns: string, min_age_days = 30): Promise<{ stale: StaleBelief[] }> =>
    j(`/api/stale?${nsq(ns)}&min_age_days=${min_age_days}`),
  claudeImport: (): Promise<{ imported: number }> => j(`/api/sessions/claude-import`),
  askAboutUser: (ns: string, question: string): Promise<{ answer?: string; insight?: string }> =>
    j(`/api/ask_user?${nsq(ns)}&q=${encodeURIComponent(question)}`),

  demoStatus: (): Promise<{ present: boolean; count: number }> => j(`/api/demo`),

  // ---- writes (loopback-trusted, or bearer when remote) ----
  seedDemo: () => post("/api/demo/seed", {}),
  clearDemo: (): Promise<{ ok: boolean; deleted: number }> => post("/api/demo/clear", {}),
  importBundle: (ns: string, bundle: any) => post("/api/import-bundle", { namespace: wns(ns) || ns, bundle }),
  renameSession: (session_id: string, name: string) => post("/api/sessions/rename", { session_id, name }),
  clearMemories: (ns: string, opts: { layer?: string; older_than_days?: number; purge_all?: boolean }): Promise<ClearResult> =>
    post<ClearResult>("/api/clear", { namespace: wns(ns) || ns, ...opts }),
  remember: (ns: string, text: string) => post("/api/remember", { namespace: wns(ns), text }),
  add: (ns: string, text: string, kind: "memory" | "observation"): Promise<AddResult> =>
    post<AddResult>("/api/add", { namespace: wns(ns), text, kind }),
  observeUser: (ns: string, text: string) => post("/api/observe_user", { namespace: wns(ns), text }),
  observePeer: (ns: string, observer: string, observed: string, text: string) =>
    post("/api/observe_peer", { namespace: wns(ns), observer, observed, text }),
  forget: (ns: string, id: string) => post("/api/forget", { namespace: wns(ns), id }),
};

export interface SessionParticipant { name: string; role?: string; metrics?: Record<string, any>; }
export interface SessionRecordMeta { title?: string; status?: string; participants?: SessionParticipant[]; metrics?: Record<string, any>; links?: Record<string, string>; }
export interface SessionItem { id: string; namespace: string; count: number; first: string | null; last: string | null; source?: string | null; name?: string; continuity?: number; record?: SessionRecordMeta | null; }
export interface DreamReport { timestamp: string; namespace: string; episodic_processed: number; distilled: number; graph_edges: number; reinforced: number; forgotten: number; derived: number; inferred: number; user_synthesized: boolean; }
export interface ContestedPair { current: Memory; superseded: Memory; confidence_new: number; confidence_old: number; surprise_score: number; }
export interface SurpriseEvent extends Memory { surprise_score: number; }
export interface ForgetCurveEntry { id: string; content: string; current_retention: number; current_strength: number; projected_strength_7d: number; days_since_recall: number; importance: number; layer: string; }
export interface PeerPair { namespace: string; observer: string; observed: string; count: number; }
export interface Contradiction { subject: string; predicate: string; history: { object: string; valid_from?: string; valid_to?: string; current: boolean }[]; }
export interface DiffItem { content: string; layer: Layer; created_at: string; namespace?: string; }

// when "all" is selected, a write has no single target → let the server use its
// default namespace; otherwise scope to the selected agent.
const wns = (ns: string) => (ns === ALL ? undefined : ns);
const post = async <T = any>(path: string, body: any): Promise<T> => {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return r.json();
};

export interface StaleBelief { id: string; content: string; age_days: number; confidence: number; namespace?: string; }
export interface ClearResult { ok: boolean; deleted: number; namespace: string; }

export const tShort = (s?: string | null) => (s || "").replace("T", " ").replace("Z", "").slice(0, 16);
export const ALL = "__all__";
