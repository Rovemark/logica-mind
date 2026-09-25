/** Tiny typed client for a running Logica Mind service (`logica-mind ui` /
 *  the PM2 service). Mirrors the REST API; every call is a plain fetch — no
 *  dependencies, works in Node 18+, Bun, Deno and the browser.
 *
 *  ```ts
 *  import { LogicaMind } from "@logica-mind/client";
 *  const mind = new LogicaMind({ base: "http://127.0.0.1:8420", namespace: "my-agent" });
 *  await mind.remember("The user prefers concise answers in Portuguese.");
 *  const hits = await mind.recall("what language should I use?");
 *  const block = await mind.context("language preferences", 1200);
 *  ```
 */

export interface MindOptions {
  /** service base URL (default http://127.0.0.1:8420) */
  base?: string;
  /** memory namespace (default "default") */
  namespace?: string;
  /** bearer token when the service runs non-loopback with LOGICA_MIND_TOKEN */
  token?: string;
  /** per-request timeout in ms (default 15000) */
  timeoutMs?: number;
}

export interface Memory {
  id: string; namespace: string; content: string; layer: string;
  importance?: number; tags?: string[]; metadata?: Record<string, unknown>;
  created_at?: string;
}
export interface RecallHit { score: number; components?: Record<string, number>; memory: Memory; }
export interface Stats { episodic: number; semantic: number; graph: number; user: number; total: number; }
export interface GraphNode {
  id: string; namespaces?: string[]; shared?: boolean; degree?: number; centrality?: number;
  dimension?: string; type?: string; channel?: string; source?: string; project?: string; squad?: string;
}
export interface GraphLink { source: string; target: string; label: string; kind?: string; valid?: boolean; weight?: number; }
export interface GraphData { nodes: GraphNode[]; links: GraphLink[]; }

export class LogicaMind {
  readonly base: string;
  readonly namespace: string;
  private token?: string;
  private timeoutMs: number;

  constructor(opts: MindOptions = {}) {
    this.base = (opts.base ?? "http://127.0.0.1:8420").replace(/\/$/, "");
    this.namespace = opts.namespace ?? "default";
    this.token = opts.token;
    this.timeoutMs = opts.timeoutMs ?? 15000;
  }

  private async req<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), this.timeoutMs);
    try {
      const headers: Record<string, string> = { "content-type": "application/json" };
      if (this.token) headers.authorization = `Bearer ${this.token}`;
      const r = await fetch(this.base + path, {
        method, headers, signal: ctrl.signal,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!r.ok) throw new Error(`logica-mind ${r.status} ${path}`);
      return (await r.json()) as T;
    } finally {
      clearTimeout(t);
    }
  }

  private q(params: Record<string, string | number | undefined>): string {
    const s = new URLSearchParams({ namespace: this.namespace });
    for (const [k, v] of Object.entries(params)) if (v !== undefined) s.set(k, String(v));
    return s.toString();
  }

  /** service liveness (`GET /api/health`) */
  health(): Promise<{ ok: boolean }> { return this.req("GET", "/api/health"); }

  /** per-layer counts for the namespace */
  async stats(): Promise<Stats> {
    const r = await this.req<{ stats: Stats }>("GET", `/api/stats?${this.q({})}`);
    return r.stats;
  }

  /** store a durable fact (extraction/dedup happen server-side) */
  remember(text: string, opts: { metadata?: Record<string, unknown>; session?: string } = {}) {
    return this.req("POST", "/api/remember", { namespace: this.namespace, text, ...opts });
  }

  /** store a raw episodic turn/event — tag `channel` to fuel the graph's channel facet */
  log(text: string, opts: { role?: string; channel?: string; session?: string; metadata?: Record<string, unknown> } = {}) {
    return this.req("POST", "/api/log", { namespace: this.namespace, text, ...opts });
  }

  /** ranked hybrid recall (graph-aware: neighbours of query entities rank up) */
  async recall(query: string, limit = 8): Promise<RecallHit[]> {
    const r = await this.req<{ results: RecallHit[] }>(
      "GET", `/api/recall?${this.q({ q: query, limit })}`);
    return r.results ?? (r as unknown as RecallHit[]);
  }

  /** prompt-ready context block fitted to a token budget (user model + graph facts + memories) */
  async context(query: string, budget = 1500): Promise<string> {
    const r = await this.req<{ block: string }>(
      "GET", `/api/context?${this.q({ q: query, budget })}`);
    return r.block;
  }

  /** the knowledge graph (nodes carry dimension/type/channel/source/project/squad facets) */
  graph(opts: { limit?: number } = {}): Promise<GraphData> {
    return this.req("GET", `/api/graph?${this.q({ limit: opts.limit })}`);
  }

  /** rename / merge an entity (non-destructive alias) */
  entityAlias(variant: string, canonical: string) {
    return this.req("POST", "/api/entity/alias", { namespace: this.namespace, variant, canonical });
  }
}

export default LogicaMind;
