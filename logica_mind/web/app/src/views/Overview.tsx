import { useEffect, useState } from "react";
import HaloLoading from "../components/HaloLoading";
import Empty from "../components/Empty";
import { api, LAYERS, type Memory, type Stats } from "../api";
import MemoryCard from "../components/MemoryCard";
import InsightList from "../components/InsightList";
import { useI18n } from "../i18n";
import { useTick } from "../anim";
import { num } from "../fmt";

export default function Overview({ ns }: { ns: string }) {
  const { t } = useI18n();
  const [stats, setStats] = useState<Stats | null>(null);
  const [insight, setInsight] = useState("");
  const [recent, setRecent] = useState<Memory[]>([]);
  const [loaded, setLoaded] = useState(false);
  // separado de `stats` porque `stats === null` também é o estado de ERRO — e um
  // esqueleto pulsando pra sempre depois de uma falha é pior que mostrar 0.
  const [statsPronto, setStatsPronto] = useState(false);

  useEffect(() => {
    setLoaded(false); setStatsPronto(false);
    api.stats(ns).then((d) => setStats(d.stats)).catch(() => setStats(null)).finally(() => setStatsPronto(true));
    api.reflect(ns).then((d) => setInsight(d.insight || "")).catch(() => setInsight(""));
    api.memories(ns).then((d) => setRecent(d.memories.slice(0, 8))).catch(() => setRecent([])).finally(() => setLoaded(true));
  }, [ns]);

  return (
    <div className="fadein">
      <h2 className="m-0 mb-4 text-[18px] font-bold tracking-tight">{t("overview")}</h2>
      <div className="grid gap-3 mb-5" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(120px,1fr))" }}>
        <Stat k={t("total")} v={stats?.total ?? 0} pronto={statsPronto} />
        {LAYERS.map((l) => <Stat key={l} k={t(`layer_${l}` as any)} v={(stats as any)?.[l] ?? 0} cls={`lyr-${l}`} pronto={statsPronto} />)}
      </div>
      {insight && (
        <>
          <div className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px] mb-2.5">{t("insight")}</div>
          <div className="mb-[18px]"><InsightList text={insight} /></div>
        </>
      )}
      <div className="text-[var(--dim2)] text-[12px] uppercase tracking-[.7px] mb-2.5">{t("recent_activity")}</div>
      {!loaded ? <HaloLoading size={84} className="py-10" />
        /* lm-cascata: os cartões entram em sequência (22ms entre eles) em vez de
           surgirem como um bloco só — responde "a lista chegou inteira?".
           Precisam ser filhos DIRETOS do wrapper pro nth-child valer. */
        : recent.length ? <div className="lm-cascata">{recent.map((m) => <MemoryCard key={m.id} m={m} />)}</div>
        /* Era uma frase cinza solta no meio da página — lê como erro. O bloco
           Empty (halo apagado + frase) lê como resposta do sistema: "vazio de
           verdade", não "quebrou". */
        : <Empty text={t("no_memories_yet")} />}
    </div>
  );
}

function Stat({ k, v, cls, pronto = true }: { k: string; v: number; cls?: string; pronto?: boolean }) {
  // PERGUNTA: "esse número mudou agora?" — pisca só quando o valor MUDA (240ms).
  const piscar = useTick(v);
  return (
    <div className="card-surface px-[17px] py-[15px]">
      <div className="text-[var(--dim)] text-[11px] uppercase tracking-[.6px]">{k}</div>
      <div className={`text-[26px] font-bold mt-0.5 tabular-nums leading-[1.25] ${cls || ""}`}>
        {/* Enquanto a contagem não chegou, esqueleto — NUNCA "0". A altura (19px)
            é a da linha do número, pra o cartão não pular de tamanho quando o
            valor entrar; 84px de largura é a de um número de 6 dígitos, o teto
            real deste appliance. */}
        {pronto ? <span className={piscar}>{num(v)}</span>
                : <span className="lm-esqueleto w-[84px] h-[19px] align-middle" aria-hidden />}
      </div>
    </div>
  );
}
