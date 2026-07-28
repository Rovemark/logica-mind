import { useEffect, useState } from "react";
import HaloLoading from "../components/HaloLoading";
import Empty from "../components/Empty";
import { Database, Network, GitBranch, Users, MessagesSquare, AlertTriangle, Gauge, Activity, ShieldCheck } from "lucide-react";
import { api, tShort, type AnalyticsData } from "../api";
import Pager, { paginate } from "../components/Pager";
import { useI18n } from "../i18n";
import { useNav } from "../navctx";
import { num, ms } from "../fmt";

const RANGES: [string, number][] = [["7d", 7], ["30d", 30], ["90d", 90]];

// namespaces are free-form; we classify each by a light naming convention
// (kind:name) so the lake reads like a typed catalog — defaults to AGENT.
// Cores por TOKEN, não hex cru: os valores antigos (#a78bfa, #22d3ee, #f59e0b,
// #7c9cff) não existem no Brand Kit e, principalmente, não tinham versão clara —
// sobre o Ivory do tema claro viravam pastel-sobre-pastel, ilegíveis num monitor
// com sol. Os tokens trocam sozinhos com o tema.
const TYPE_COLOR: Record<string, string> = {
  USER: "var(--graph)", ORG: "var(--good)", DOMAIN: "var(--gold)", AGENT: "var(--accent)",
};
function nsType(name: string): string {
  const n = name.toLowerCase();
  if (n.startsWith("user:") || n === "user" || n.includes("profile")) return "USER";
  if (n.startsWith("org:") || n.includes("company") || n.includes("acme")) return "ORG";
  if (n.startsWith("domain:") || n.includes("docs") || n.includes("kb")) return "DOMAIN";
  return "AGENT";
}

// A camada tem UMA cor no sistema inteiro (a mesma da pílula em /memories e da
// aresta no grafo). Por isso vem dos tokens --episodic/--semantic/--graph/--user
// em vez de hex repetido: quando a cor da camada mudar, muda num lugar só.
const LAYER_COLOR: Record<string, string> = {
  episodic: "var(--episodic)", semantic: "var(--semantic)", graph: "var(--graph)", user: "var(--user)",
};

// Série categórica do Brand Kit: 5 famílias, TODAS por token — Sovereign Blue,
// verde de estado, Logic Amber, violeta do grafo e Steel.
// Eram 6 hexes crus; dois (#f472b6 rosa, #22d3ee ciano) sequer existem no kit, e
// nenhum tinha versão para o tema claro. Cinco famílias distintas bastam: cada
// barra já carrega o rótulo ao lado, então a cor separa, não nomeia.
const SRC_COLOR = ["var(--accent)", "var(--good)", "var(--gold)", "var(--graph)", "var(--dim)"];

// ---- stat card ----
function Stat({ icon: Icon, label, value, color = "var(--accent)", sub }:
  { icon: any; label: string; value: string | number; color?: string; sub?: string }) {
  return (
    // title no rótulo: mesmo com a faixa larga, num monitor estreito o texto
    // ainda pode cortar — o hover devolve o nome inteiro em vez de deixar
    // "CONTRADI…" sem resposta.
    <div className="card-surface px-4 py-3.5 min-w-0">
      <div className="flex items-center gap-1.5 mb-1.5" title={label}>
        <Icon size={13} style={{ color }} className="flex-none" />
        <span className="text-[10px] text-[var(--dim2)] uppercase tracking-[.6px] truncate">{label}</span>
      </div>
      {/* leading-tight (era leading-none): com line-height 1 o "9" e o "g" de
          alguns pesos do Manrope encostavam na borda do número. */}
      <div className="text-[22px] font-bold tabular-nums leading-tight truncate" style={{ color }} title={String(value)}>{value}</div>
      {sub && <div className="text-[10.5px] text-[var(--dim2)] mt-1 truncate">{sub}</div>}
    </div>
  );
}

// ---- vertical bars over time ----
function TimeBars({ data, title, sub }: { data: { date: string; count: number }[]; title: string; sub?: string }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  const total = data.reduce((a, d) => a + d.count, 0);
  return (
    <div className="card-surface p-4">
      <div className="flex items-baseline gap-2 mb-0.5">
        <span className="text-[13px] font-semibold">{title}</span>
        <span className="ml-auto text-[11px] text-[var(--dim2)] tabular-nums">{num(total)}</span>
      </div>
      {sub && <div className="text-[11px] text-[var(--dim2)] mb-3">{sub}</div>}
      <div className="flex items-end gap-[3px] h-[120px]">
        {data.map((d, i) => (
          // A barra é fina demais pra ter rótulo; o title é a única resposta pra
          // "quanto foi NESSE dia?". transition-colors 150ms: a barra sob o
          // cursor se destaca antes de o tooltip do sistema aparecer (que demora
          // ~1s) — sem isso o dono não sabe qual barra ele está lendo.
          <div key={i} title={`${d.date.slice(5)} · ${num(d.count)}`}
            className="flex-1 rounded-t-[3px] bg-gradient-to-t from-[var(--accent)]/55 to-[var(--accent)] hover:to-[var(--accent2)] transition-colors duration-150 min-h-[2px]"
            style={{ height: `${Math.max(2, (d.count / max) * 100)}%` }} />
        ))}
      </div>
      <div className="flex justify-between text-[10px] text-[var(--dim2)] mt-1.5">
        <span>{data[0]?.date.slice(5)}</span><span>{data[data.length - 1]?.date.slice(5)}</span>
      </div>
    </div>
  );
}

// ---- horizontal bars (distribution) ----
function HBars({ rows, title }: { rows: { label: string; value: number; color: string }[]; title: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="card-surface p-4">
      <div className="text-[13px] font-semibold mb-3">{title}</div>
      <div className="flex flex-col gap-2.5">
        {rows.length === 0 && <div className="text-[var(--dim)] text-[12px] py-6 text-center">—</div>}
        {rows.map((r, i) => (
          <div key={i}>
            <div className="flex items-center gap-2 text-[12px] mb-1">
              <span className="w-2 h-2 rounded-full flex-none" style={{ background: r.color }} />
              <span className="text-[var(--dim)] truncate" title={r.label}>{r.label}</span>
              <span className="ml-auto tabular-nums font-semibold text-[var(--txt)]">{num(r.value)}</span>
            </div>
            {/* transition-[width] no lugar de transition-all: `all` anima
                TAMBÉM a cor de fundo quando o tema troca — o gráfico inteiro
                "derretia" de uma paleta pra outra. Aqui só a largura cresce, que
                é a única coisa que significa alguma coisa. 200ms: dentro do teto
                da casa e rápido o bastante pra ler como "o dado chegou" e não
                como enchimento. */}
            <div className="h-[6px] rounded-full bg-[var(--panel2)] overflow-hidden">
              <div className="h-full rounded-full transition-[width] duration-200 ease-out"
                style={{ width: `${(r.value / max) * 100}%`, background: r.color }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- inline sparkline (svg) ----
function Spark({ values, color = "var(--accent2)" }: { values: number[]; color?: string }) {
  const max = Math.max(1, ...values);
  const w = 92, h = 22, n = values.length;
  const bw = w / n;
  return (
    <svg width={w} height={h} className="block">
      {values.map((v, i) => {
        const bh = Math.max(1, (v / max) * (h - 2));
        return <rect key={i} x={i * bw + 0.5} y={h - bh} width={bw - 1.2} height={bh} rx={1}
          fill={color} opacity={v ? 0.85 : 0.18} />;
      })}
    </svg>
  );
}

export default function Analytics({ ns, colorFor }: { ns: string; colorFor: (n: string) => string }) {
  const { t } = useI18n();
  const { onNs } = useNav();
  const [d, setD] = useState<AnalyticsData | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [range, setRange] = useState(30);
  const [lpage, setLpage] = useState(1);

  useEffect(() => {
    setLoaded(false);
    api.analytics(ns, range).then((r) => { setD(r); setLoaded(true); }).catch(() => setLoaded(true));
  }, [ns, range]);

  if (!loaded) return <div className="fadein py-16"><HaloLoading size={96} /></div>;
  // Bloco Empty no lugar da frase cinza solta: "vazio de verdade" ≠ "quebrou".
  if (!d) return <div className="fadein py-10"><Empty text={t("nothing_here")} /></div>;

  const tot = d.totals;
  const layerRows = ["episodic", "semantic", "graph", "user"]
    .map((l) => ({ label: t(`layer_${l}` as any), value: tot[l] || 0, color: LAYER_COLOR[l] }));
  const sourceRows = d.by_source.map((s, i) => ({ label: s.source, value: s.count, color: SRC_COLOR[i % SRC_COLOR.length] }));
  const agentRows = d.by_namespace.slice(0, 8).map((r) => ({ label: r.namespace, value: r.total, color: colorFor(r.namespace) }));
  const lake = paginate(d.by_namespace, lpage, 12);

  return (
    <div className="fadein">
      <div className="flex items-baseline gap-3 mb-4">
        <h2 className="m-0 text-[18px] font-bold tracking-tight">{t("analytics")}</h2>
        <span className="text-[var(--dim2)] text-[12px] max-[680px]:hidden">{t("analytics_sub")}</span>
        {/* PERGUNTA: "esses números são de quantos dias?"
            O recorte ativo era cinza-sobre-cinza (panel2 + line) — a mesma
            família visual do inativo, dava pra ler o gráfico achando que era
            "todos" quando eram 30 dias. Agora o ativo usa o azul da marca, o
            MESMO tratamento dos chips de camada em /memories (duas telas, uma
            linguagem só), e o inativo se anuncia no hover ANTES do clique.
            transition-colors 150ms: troca de cor, não de posição. */}
        <div className="ml-auto flex gap-1">
          {[...RANGES, [t("all_word"), 0] as [string, number]].map(([l, dval]) => (
            <button key={l} onClick={() => setRange(dval)}
              className={`px-2.5 py-1 rounded-lg border text-[12px] tabular-nums transition-colors duration-150
                ${range === dval ? "bg-[var(--accent)]/12 text-[var(--accent)] border-[var(--accent)] font-semibold"
                                 : "border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)] hover:border-[var(--dim2)] hover:bg-[var(--panel2)]"}`}>{l}</button>
          ))}
        </div>
      </div>

      {/* stat strip */}
      {/* minmax 112 → 138px: com 112 os rótulos cortavam ("AGENTES …",
          "CONTRADI…", "TAXA DE E…") e um número sem rótulo legível não responde
          NADA. 138px é a largura de "CONTRADIÇÕES" em 10px/tracking .6. */}
      <div className="grid gap-2.5 mb-3" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(138px,1fr))" }}>
        <Stat icon={Database} label={t("memories")} value={num(tot.memories ?? 0)} color="var(--accent)" />
        <Stat icon={Users} label={t("agents_clones")} value={num(tot.namespaces ?? 0)} color="var(--accent2)" />
        <Stat icon={Network} label={t("graph_entities")} value={num(tot.entities ?? 0)} color="var(--graph)" />
        <Stat icon={GitBranch} label={t("relations")} value={num(tot.relations ?? 0)} color="var(--graph)" />
        <Stat icon={MessagesSquare} label={t("sessions")} value={num(tot.sessions ?? 0)} color="var(--gold)" />
        {/* PERGUNTA: "isso é um alarme?"
            Era #fb7185 — vermelho. O Brand Kit da LogicaOS NÃO TEM vermelho: o
            sinal de atenção do sistema é o Logic Amber (var(--warn)). Além da
            marca, o vermelho mentia sobre a gravidade: contradição num sistema
            de memória é uma crença SUPERADA, o comportamento normal e desejado
            de quem aprende — não uma falha. Âmbar diz "olhe", vermelho diz
            "quebrou". */}
        <Stat icon={AlertTriangle} label={t("contradictions").split(" ")[0]} value={num(tot.contradictions ?? 0)} color="var(--warn)" />
        {/* ms(): "19153.7ms" não cabia no cartão E não tem escala mental —
            vira "19,2s". Mesma medida, escrita pra ser lida. */}
        <Stat icon={Gauge} label={t("avg_latency")} value={ms(d.ops.avg_latency_ms)} color="var(--accent)" sub={`${num(d.ops.requests)} ${t("requests_word")}`} />
        {/* mesma regra: alarme é âmbar, "está tudo certo" é o verde de estado
            que o resto do painel já usa (var(--good)) — e que, ao contrário do
            #4ade80, escurece sozinho no tema claro em vez de sumir no Ivory. */}
        <Stat icon={Activity} label={t("error_rate")} value={`${d.ops.error_rate}%`} color={d.ops.error_rate > 1 ? "var(--warn)" : "var(--good)"} />
      </div>

      {/* 2x2 chart grid */}
      <div className="grid grid-cols-2 gap-2.5 mb-3 max-[760px]:grid-cols-1">
        <TimeBars data={d.timeseries} title={t("memories_over_time")} sub={range === 0 ? t("all_time") : t("last_n_days", { n: String(range) })} />
        <HBars rows={layerRows} title={t("by_layer")} />
        <HBars rows={sourceRows} title={t("by_source")} />
        <HBars rows={agentRows} title={t("by_agent")} />
      </div>

      {/* Context-lake-style table */}
      <div className="card-surface overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--line)] flex items-center gap-2">
          <span className="text-[12px] font-semibold">{t("memory_lake")}</span>
          {/* num(): o rodapé do lago dizia "85308" enquanto o cartão do topo da
              MESMA tela dizia "85.308". Dois formatos pro mesmo número fazem o
              dono conferir se está lendo a mesma coisa. */}
          <span className="ml-auto text-[11px] text-[var(--dim2)] tabular-nums">{num(tot.memories ?? 0)} {t("memories_word")}</span>
        </div>
        <div className="grid grid-cols-[1fr_72px_72px_72px_110px_84px] gap-2 px-4 py-2 text-[10px] uppercase tracking-[.6px] text-[var(--dim2)] border-b border-[var(--line)] max-[680px]:grid-cols-[1fr_60px_92px]">
          <span>{t("lake_subject")}</span>
          <span className="text-right max-[680px]:hidden">{t("lake_entities")}</span>
          <span className="text-right">{t("lake_facts")}</span>
          <span className="text-right max-[680px]:hidden">{t("relations")}</span>
          <span className="max-[680px]:hidden">{t("lake_activity")}</span>
          <span className="text-right max-[680px]:hidden">{t("lake_updated")}</span>
        </div>
        {lake.slice.map((r) => (
          <div key={r.namespace} onClick={() => onNs(r.namespace)} title={r.namespace}
            className="grid grid-cols-[1fr_72px_72px_72px_110px_84px] gap-2 px-4 py-2.5 items-center border-b border-[var(--line)] last:border-0 hover:bg-[var(--panel2)] cursor-pointer max-[680px]:grid-cols-[1fr_60px_92px]">
            <span className="flex items-center gap-2 min-w-0">
              <span className="w-2 h-2 rounded-full flex-none" style={{ background: colorFor(r.namespace) }} />
              <span className="font-semibold text-[13px] truncate">{r.namespace}</span>
              {/* color-mix no lugar do antigo `${c}1f`: concatenar opacidade em
                  hex só funciona com hex cru. Como a cor virou token, o fundo a
                  12% agora é calculado — e continua acompanhando o tema. */}
              {(() => { const ty = nsType(r.namespace), c = TYPE_COLOR[ty]; return (
                <span className="text-[9px] font-bold tracking-wide px-1.5 py-px rounded-full flex-none"
                  style={{ background: `color-mix(in srgb, ${c} 12%, transparent)`, color: c }}>{ty}</span>
              ); })()}
            </span>
            {/* num() nas três colunas: são as contagens por agente e passavam de
                mil sem separador ("12480"). É a mesma pergunta do cartão do topo
                — "é mil ou dez mil?" — só que aqui repetida em 12 linhas. */}
            <span className="text-right tabular-nums text-[12.5px] text-[var(--dim)] max-[680px]:hidden">{num(r.entities)}</span>
            <span className="text-right tabular-nums text-[12.5px] text-[var(--dim)]">{num(r.facts)}</span>
            <span className="text-right tabular-nums text-[12.5px] text-[var(--dim)] max-[680px]:hidden">{num(r.relations)}</span>
            <span className="max-[680px]:hidden"><Spark values={r.spark} color={colorFor(r.namespace)} /></span>
            <span className="text-right text-[11px] text-[var(--dim2)] tabular-nums max-[680px]:hidden">{tShort(r.last)?.slice(0, 10)}</span>
          </div>
        ))}
        {lake.pages > 1 && <div className="px-4 pb-2"><Pager page={lake.page} pages={lake.pages} onPage={setLpage} /></div>}
        {/* governance footer — the real guarantees every row carries */}
        <div className="px-4 py-2.5 border-t border-[var(--line)] flex items-center gap-1.5 flex-wrap">
          <ShieldCheck size={12} className="text-[var(--good)] flex-none" />
          {["gov_provenance", "gov_sourced", "gov_versioned", "gov_erase"].map((k) => (
            <span key={k} className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-[var(--panel2)] border border-[var(--line)] text-[var(--dim)]">{t(k)}</span>
          ))}
          <span className="text-[10.5px] text-[var(--dim2)] ml-1 max-[680px]:hidden">{t("gov_note")}</span>
        </div>
      </div>
    </div>
  );
}
