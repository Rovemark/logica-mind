import { useEffect, useMemo, useState } from "react";
import {
  Database, Table2, KeyRound, Gauge, Inbox, ChevronLeft, ChevronRight,
  AlertTriangle, Activity,
} from "lucide-react";
import { useI18n } from "../i18n";
import { banco, type BancoTabela, type BancoIndice, type BancoSaude, type BancoLinhas, type BancoPendente, type Esquema } from "../api";

/* A camada estruturada do Logica Mind, olhada de perto.
   Construir o Banco de dados inteiro sem tela foi um erro: dava pra falar com ele por
   HTTP e não dava pra VER. E ver é como se descobre que a migração trouxe tudo, ou que
   um índice existe e nunca é escolhido. */

type Aba = "tabelas" | "linhas" | "indices" | "fila" | "saude";

const num = (n: number) => n.toLocaleString("pt-BR");

function Aviso({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-[10px] border border-[var(--line)] bg-[var(--panel2)] px-3 py-2.5 text-[12.5px] text-[var(--dim)]">
      <AlertTriangle size={14} className="mt-px shrink-0 text-[var(--warn,#E99A2E)]" />
      <span>{children}</span>
    </div>
  );
}

/* Célula: o valor cru do Postgres em texto legível, sem esconder o que ele é.
   jsonb vira JSON curto, timestamp vira data, bytea já vem como "<N bytes>". */
function Celula({ v }: { v: unknown }) {
  if (v === null || v === undefined)
    return <span className="mono text-[11px] text-[var(--dim2)]">null</span>;
  if (typeof v === "boolean")
    return <span className="mono text-[11.5px]">{v ? "true" : "false"}</span>;
  if (typeof v === "object") {
    const s = JSON.stringify(v);
    return <span className="mono text-[11.5px] text-[var(--dim)]" title={s}>{s.length > 90 ? s.slice(0, 90) + "…" : s}</span>;
  }
  const s = String(v);
  const data = /^\d{4}-\d{2}-\d{2}T/.test(s);
  return (
    <span className={data ? "mono text-[11.5px] text-[var(--dim)]" : "text-[12.5px]"} title={s.length > 60 ? s : undefined}>
      {s.length > 70 ? s.slice(0, 70) + "…" : s}
    </span>
  );
}

export default function Banco() {
  const { t } = useI18n();
  const [aba, setAba] = useState<Aba>("tabelas");
  const [tabelas, setTabelas] = useState<BancoTabela[] | null>(null);
  const [sistema, setSistema] = useState<BancoTabela[] | null>(null);
  const [esq, setEsq] = useState<Esquema>("banco");
  const [indices, setIndices] = useState<BancoIndice[] | null>(null);
  const [saude, setSaude] = useState<BancoSaude | null>(null);
  const [fila, setFila] = useState<BancoPendente[] | null>(null);
  const [alvo, setAlvo] = useState<string>("linha");
  const [dados, setDados] = useState<BancoLinhas | null>(null);
  const [desloc, setDesloc] = useState(0);
  const [erro, setErro] = useState("");
  const [carregando, setCarregando] = useState(true);

  const totalVida = useMemo(() => (tabelas || []).reduce((s, x) => s + x.total, 0), [tabelas]);
  const totalSistema = useMemo(() => (sistema || []).reduce((s, x) => s + x.total, 0), [sistema]);
  const listaAtual = esq === "banco" ? (tabelas || []) : (sistema || []);

  useEffect(() => {
    setCarregando(true); setErro("");
    Promise.all([banco.tabelas("banco"), banco.tabelas("sistema"), banco.saude()])
      .then(([tb, sy, sd]) => { setTabelas(tb); setSistema(sy); setSaude(sd); })
      .catch((e) => setErro(String(e)))
      .finally(() => setCarregando(false));
  }, []);

  useEffect(() => {
    if (aba === "indices" && !indices) banco.indices().then(setIndices).catch((e) => setErro(String(e)));
    if (aba === "fila" && !fila) banco.pendentes().then(setFila).catch((e) => setErro(String(e)));
  }, [aba, indices, fila]);

  // Trocar de esquema tem que trocar a tabela junto. Sem isto, sair de `banco` com
  // `linha` selecionada e entrar em `sistema` pede uma tabela que não existe lá: erro
  // na tela e grade vazia. E o conserto tem que morar AQUI, não em cada botão, porque
  // a troca acontece em dois lugares (o seletor da aba Tabelas e o da aba Navegar).
  useEffect(() => {
    if (!listaAtual.length) return;
    if (!listaAtual.some((x) => x.nome === alvo)) { setAlvo(listaAtual[0].nome); setDesloc(0); }
  }, [esq, listaAtual, alvo]);

  useEffect(() => {
    if (aba !== "linhas") return;
    if (!listaAtual.some((x) => x.nome === alvo)) return;   // espera o alvo alinhar
    setErro("");
    banco.tabela(alvo, 50, desloc, esq).then(setDados).catch((e) => setErro(String(e)));
  }, [aba, alvo, desloc, esq, listaAtual]);


  const ABAS: { k: Aba; rotulo: string; Icon: typeof Table2 }[] = [
    { k: "tabelas", rotulo: t("bd_tab_tables"), Icon: Table2 },
    { k: "linhas", rotulo: t("bd_tab_browse"), Icon: Database },
    { k: "indices", rotulo: t("bd_tab_indexes"), Icon: KeyRound },
    { k: "fila", rotulo: t("bd_tab_outbox"), Icon: Inbox },
    { k: "saude", rotulo: t("bd_tab_health"), Icon: Gauge },
  ];

  return (
    <div className="fadein">
      <h2 className="m-0 mb-1 text-[18px] font-bold tracking-tight">{t("bd_title")}</h2>
      <p className="mt-0 mb-4 text-[13px] text-[var(--dim)]">{t("bd_desc")}</p>

      {erro && <div className="mb-4 text-[13px] text-[var(--warn,#E99A2E)]">{erro}</div>}
      {carregando && <div className="py-8 text-center text-[var(--dim)]">{t("loading_word")}</div>}

      {!carregando && (
        <>
          {/* resumo: o que existe, num olhar */}
          <div className="mb-5 grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(170px,1fr))" }}>
            <Cartao rotulo={t("bd_life_word")} valor={`${num(tabelas?.length || 0)} · ${num(totalVida)}`} />
            <Cartao rotulo={t("bd_system_word")} valor={`${num(sistema?.length || 0)} · ${num(totalSistema)}`} />
            <Cartao rotulo={t("bd_pool_word")}
              valor={saude ? `${saude.pool.em_uso}/${saude.pool.max}` : "—"} />
            <Cartao rotulo={t("bd_slots_word")}
              valor={saude ? `${saude.slots_livres}/${saude.slots_max}` : "—"} />
          </div>

          <div className="mb-4 flex flex-wrap gap-1.5">
            {ABAS.map(({ k, rotulo, Icon }) => (
              <button key={k} onClick={() => setAba(k)}
                className={"inline-flex items-center gap-1.5 rounded-[9px] border px-3 py-1.5 text-[12.5px] transition " +
                  (aba === k
                    ? "border-[var(--accent)] bg-[var(--accent)]/12 text-[var(--txt)]"
                    : "border-[var(--line)] text-[var(--dim)] hover:border-[var(--dim2)]")}>
                <Icon size={14} /> {rotulo}
              </button>
            ))}
          </div>

          {aba === "tabelas" && (
            <div>
              {/* A separação vem PRIMEIRO, e é uma escolha, não uma rolagem. Empilhar
                  os dois grupos punha o Sistema a 70 cartões de distância: quem abre
                  a tela precisa ver a divisão de imediato, não descobri-la rolando. */}
              <div className="mb-4 flex flex-wrap gap-2">
                {([
                  { k: "banco" as Esquema, rot: t("bd_group_life"), n: tabelas?.length || 0, l: totalVida, ro: false },
                  { k: "sistema" as Esquema, rot: t("bd_group_system"), n: sistema?.length || 0, l: totalSistema, ro: true },
                ]).map((g) => (
                  <button key={g.k} onClick={() => setEsq(g.k)}
                    className={"flex-1 min-w-[240px] rounded-[12px] border px-4 py-3 text-left transition " +
                      (esq === g.k
                        ? "border-[var(--accent)] bg-[var(--accent)]/10"
                        : "border-[var(--line)] hover:border-[var(--dim2)]")}>
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-bold uppercase tracking-[0.1em]">{g.rot}</span>
                      {g.ro && (
                        <span className="mono rounded-[5px] border border-[var(--line)] px-1.5 py-0.5 text-[9.5px] text-[var(--dim2)]">
                          {t("bd_readonly_tag")}
                        </span>
                      )}
                    </div>
                    <div className="mono mt-1 text-[11.5px] text-[var(--dim)]">
                      {g.n} {t("bd_tables_lower")} · {g.l.toLocaleString("pt-BR")} {t("bd_rows_lower")}
                    </div>
                  </button>
                ))}
              </div>

              <p className="mb-4 mt-0 max-w-[78ch] text-[12.5px] leading-snug text-[var(--dim)]">
                {esq === "banco" ? t("bd_group_life_desc") : t("bd_group_system_desc")}
              </p>

              <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(272px,1fr))" }}>
                {listaAtual.map((tb) => (
                  <button key={tb.nome}
                    onClick={() => { setAlvo(tb.nome); setDesloc(0); setAba("linhas"); }}
                    className="card-surface p-3.5 text-left transition hover:border-[var(--accent)]">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="mono truncate text-[12.5px] font-medium">{esq}.{tb.nome}</span>
                      <span className="mono shrink-0 text-[10.5px] text-[var(--dim2)]">{tb.tamanho}</span>
                    </div>
                    <div className="mt-1.5 flex items-baseline gap-1.5">
                      <span className="text-[20px] font-bold tracking-tight">{tb.total.toLocaleString("pt-BR")}</span>
                      <span className="text-[11px] text-[var(--dim)]">{t("bd_rows_lower")}</span>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {tb.colunas.slice(0, 6).map((c) => (
                        <span key={c.nome} title={c.tipo}
                          className="mono rounded-[5px] bg-[var(--panel2)] px-1.5 py-0.5 text-[9.5px] text-[var(--dim)]">
                          {c.nome}
                        </span>
                      ))}
                      {tb.colunas.length > 6 && (
                        <span className="mono px-1 py-0.5 text-[9.5px] text-[var(--dim2)]">+{tb.colunas.length - 6}</span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {aba === "linhas" && (
            <div>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {/* separação explícita: primeiro DE ONDE, depois QUAL */}
                <div className="inline-flex overflow-hidden rounded-[9px] border border-[var(--line)]">
                  {(["banco", "sistema"] as Esquema[]).map((e) => (
                    <button key={e} onClick={() => { setEsq(e); setDesloc(0); }}
                      className={"mono px-3 py-1.5 text-[11.5px] transition " +
                        (esq === e ? "bg-[var(--accent)] text-white" : "text-[var(--dim)] hover:text-[var(--txt)]")}>
                      {e}
                    </button>
                  ))}
                </div>
                <select value={alvo} onChange={(e) => { setAlvo(e.target.value); setDesloc(0); }}
                  className="mono rounded-[9px] border border-[var(--line)] bg-[var(--bg)] px-2.5 py-1.5 text-[12.5px] outline-none focus:border-[var(--accent)]">
                  {listaAtual.map((tb) => <option key={tb.nome} value={tb.nome}>{esq}.{tb.nome}</option>)}
                </select>
                {dados && (
                  <>
                    <span className="text-[12px] text-[var(--dim)]">
                      {num(dados.desloc + 1)}–{num(Math.min(dados.desloc + dados.limite, dados.total))} {t("bd_of")} {num(dados.total)}
                    </span>
                    <div className="ml-auto flex gap-1">
                      <button disabled={desloc === 0} onClick={() => setDesloc(Math.max(0, desloc - 50))}
                        className="rounded-[8px] border border-[var(--line)] p-1.5 disabled:opacity-35">
                        <ChevronLeft size={14} />
                      </button>
                      <button disabled={dados.desloc + dados.limite >= dados.total} onClick={() => setDesloc(desloc + 50)}
                        className="rounded-[8px] border border-[var(--line)] p-1.5 disabled:opacity-35">
                        <ChevronRight size={14} />
                      </button>
                    </div>
                  </>
                )}
              </div>
              {dados?.escopada && <div className="mb-3"><Aviso>{t("bd_scoped_notice")}</Aviso></div>}
              {dados?.dono && <div className="mb-3"><Aviso>{t("bd_owner_notice")}</Aviso></div>}
              {dados?.somente_leitura && <div className="mb-3"><Aviso>{t("bd_readonly_notice")}</Aviso></div>}
              {/* rolagem horizontal PRÓPRIA: tabela larga não pode empurrar a página */}
              <div className="card-surface overflow-x-auto">
                <table className="w-full border-collapse text-left">
                  <thead>
                    <tr className="border-b border-[var(--line)]">
                      {(dados?.colunas || []).map((c) => (
                        <th key={c} className="mono whitespace-nowrap px-3 py-2 text-[10.5px] uppercase tracking-[.6px] text-[var(--dim2)]">{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(dados?.linhas || []).map((l, i) => (
                      <tr key={i} className="border-b border-[var(--line)]/45 last:border-0 hover:bg-[var(--panel2)]/45">
                        {l.map((v, j) => (
                          <td key={j} className="max-w-[380px] px-3 py-2 align-top">
                            <Celula v={v} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {dados && dados.linhas.length === 0 && (
                  <div className="py-10 text-center text-[13px] text-[var(--dim)]">{t("bd_empty_table")}</div>
                )}
              </div>
            </div>
          )}

          {aba === "indices" && (
            <div>
              <div className="mb-3"><Aviso>{t("bd_index_notice")}</Aviso></div>
              <div className="card-surface overflow-x-auto">
                <table className="w-full border-collapse text-left">
                  <thead>
                    <tr className="border-b border-[var(--line)]">
                      {[t("bd_index"), t("bd_table_word"), t("bd_reads"), t("bd_size"), ""].map((h, i) => (
                        <th key={i} className="mono whitespace-nowrap px-3 py-2 text-[10.5px] uppercase tracking-[.6px] text-[var(--dim2)]">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(indices || []).map((ix) => (
                      <tr key={ix.nome} className="border-b border-[var(--line)]/45 last:border-0">
                        <td className="mono px-3 py-2 text-[12px]" title={ix.definicao}>{ix.nome}</td>
                        <td className="mono px-3 py-2 text-[12px] text-[var(--dim)]">{ix.tabela}</td>
                        <td className={"mono px-3 py-2 text-[12px] " + (ix.leituras === 0 ? "text-[var(--warn,#E99A2E)]" : "")}>
                          {num(ix.leituras)}
                        </td>
                        <td className="mono px-3 py-2 text-[12px] text-[var(--dim)]">{ix.tamanho}</td>
                        <td className="px-3 py-2">
                          {!ix.valido && <span className="mono text-[11px] text-[var(--warn,#E99A2E)]">{t("bd_invalid")}</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {aba === "fila" && (
            <div>
              <div className="mb-3"><Aviso>{t("bd_outbox_notice")}</Aviso></div>
              {(fila || []).length === 0
                ? <div className="card-surface py-10 text-center text-[13px] text-[var(--dim)]">{t("bd_outbox_empty")}</div>
                : <div className="grid gap-2">
                    {(fila || []).map((e) => (
                      <div key={e.id} className="card-surface flex flex-wrap items-center gap-3 px-4 py-3">
                        <span className="mono text-[12px] font-medium">{e.tipo}</span>
                        <span className="mono text-[11px] text-[var(--dim2)]">{e.criado_em?.slice(0, 19).replace("T", " ")}</span>
                        <span className={"mono ml-auto text-[11px] " + (e.processado_em ? "text-[var(--dim)]" : "text-[var(--accent)]")}>
                          {e.processado_em ? t("bd_done") : t("bd_pending")}
                          {e.tentativas > 0 && ` · ${e.tentativas} ${t("bd_tries")}`}
                        </span>
                        {e.erro && <div className="mono w-full text-[11px] text-[var(--warn,#E99A2E)]">{e.erro}</div>}
                      </div>
                    ))}
                  </div>}
            </div>
          )}

          {aba === "saude" && saude && (
            <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))" }}>
              <div className="card-surface p-4">
                <div className="mb-3 flex items-center gap-2 text-[11px] uppercase tracking-[.7px] text-[var(--dim2)]">
                  <Activity size={13} /> {t("bd_pool_word")}
                </div>
                <Linha rotulo={t("bd_inuse")} valor={`${saude.pool.em_uso} / ${saude.pool.max}`} />
                <Linha rotulo={t("bd_waiting")} valor={String(saude.pool.esperando)} />
                <Linha rotulo={t("bd_latency")} valor={`${saude.latencia_ms} ms`} />
              </div>
              <div className="card-surface p-4">
                <div className="mb-3 flex items-center gap-2 text-[11px] uppercase tracking-[.7px] text-[var(--dim2)]">
                  <Gauge size={13} /> {t("bd_admission")}
                </div>
                <Linha rotulo={t("bd_free_slots")} valor={`${saude.slots_livres} / ${saude.slots_max}`} />
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[var(--line)]/40">
                  <div className="h-full rounded-full bg-[var(--accent)] transition-[width] duration-300"
                    style={{ width: `${(1 - saude.slots_livres / Math.max(1, saude.slots_max)) * 100}%` }} />
                </div>
                <p className="mt-3 text-[11.5px] leading-snug text-[var(--dim)]">{t("bd_admission_desc")}</p>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Cartao({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <div className="card-surface p-4">
      <div className="text-[10.5px] uppercase tracking-[.7px] text-[var(--dim2)]">{rotulo}</div>
      <div className="mono mt-1.5 text-[22px] font-bold tracking-tight">{valor}</div>
    </div>
  );
}

function Linha({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <div className="flex items-baseline justify-between border-b border-[var(--line)]/40 py-1.5 last:border-0">
      <span className="text-[12.5px] text-[var(--dim)]">{rotulo}</span>
      <span className="mono text-[12.5px]">{valor}</span>
    </div>
  );
}
