/**
 * Logica Mind — thin TypeScript client.
 *
 * Talks to a running Logica Mind server (`logica-mind ui --no-open`, default
 * http://localhost:8420). Gives any TS/JS app the memory brain over a tiny REST
 * surface. Zero dependencies (uses global fetch, Node 18+ / browsers).
 *
 *   const mind = new LogicaMind({ namespace: "agent" });
 *   await mind.remember("The user prefers concise answers.");
 *   const hits = await mind.recall("how should I answer?");
 */

export interface Memory {
  id: string;
  content: string;
  layer: "episodic" | "semantic" | "graph" | "user";
  namespace: string;
  tags?: string[];
  created_at?: string;
}

export interface RecallHit {
  score: number;
  components?: Record<string, number>;
  memory: Memory;
}

export interface LogicaMindOptions {
  baseUrl?: string;
  namespace?: string;
  fetch?: typeof fetch;
}

export class LogicaMind {
  private baseUrl: string;
  private namespace: string;
  private _fetch: typeof fetch;

  constructor(opts: LogicaMindOptions = {}) {
    this.baseUrl = (opts.baseUrl ?? "http://localhost:8420").replace(/\/$/, "");
    this.namespace = opts.namespace ?? "default";
    this._fetch = opts.fetch ?? fetch;
  }

  private async post<T>(path: string, body: Record<string, unknown>): Promise<T> {
    const res = await this._fetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ namespace: this.namespace, ...body }),
    });
    return res.json() as Promise<T>;
  }

  private async get<T>(path: string, params: Record<string, string> = {}): Promise<T> {
    const q = new URLSearchParams({ namespace: this.namespace, ...params });
    const res = await this._fetch(`${this.baseUrl}${path}?${q.toString()}`);
    return res.json() as Promise<T>;
  }

  /** Store a durable fact/note (automatic extraction + dedup happen server-side). */
  remember(text: string, session?: string): Promise<{ stored: string[]; count: number }> {
    return this.post("/api/remember", { text, session });
  }

  /** Store a raw episodic turn. */
  log(text: string, role?: string, session?: string): Promise<{ ok: boolean; id: string | null }> {
    return this.post("/api/log", { text, role, session });
  }

  /** Delete by id or by semantic query. */
  forget(opts: { id?: string; query?: string }): Promise<{ deleted: number }> {
    return this.post("/api/forget", opts);
  }

  /** Retrieve the most relevant memories. */
  async recall(query: string, limit = 8): Promise<RecallHit[]> {
    const d = await this.get<{ results: RecallHit[] }>("/api/recall", { q: query, limit: String(limit) });
    return d.results ?? [];
  }

  /** Per-layer counts. */
  stats(): Promise<{ namespace: string; stats: Record<string, number> }> {
    return this.get("/api/stats");
  }

  /** Temporal knowledge graph (nodes + links). */
  graph(history = true): Promise<{ nodes: unknown[]; links: unknown[] }> {
    return this.get("/api/graph", { history: history ? "1" : "0" });
  }

  /** The dialectic user model. */
  async user(): Promise<string> {
    const d = await this.get<{ profile: string }>("/api/user");
    return d.profile ?? "";
  }
}

export default LogicaMind;
