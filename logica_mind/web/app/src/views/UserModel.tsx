import { useEffect, useRef, useState } from "react";
import { Send } from "lucide-react";
import { api } from "../api";
import Markdown from "../components/Markdown";
import { useI18n } from "../i18n";

export default function UserModel({ ns }: { ns: string }) {
  const { t } = useI18n();
  const [profile, setProfile] = useState("");
  const [name, setName] = useState(ns);
  const [q, setQ] = useState("");
  const [answer, setAnswer] = useState("");
  const [asking, setAsking] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setAnswer("");
    api.user(ns).then((d) => { setProfile(d.profile || ""); setName(d.namespace); }).catch(() => setProfile(""));
  }, [ns]);

  async function ask() {
    if (!q.trim() || asking) return;
    setAsking(true); setAnswer("");
    try {
      const res = await api.askAboutUser(ns, q.trim());
      setAnswer(res.answer || res.insight || JSON.stringify(res));
    } catch { setAnswer("—"); }
    setAsking(false);
  }

  return (
    <div className="fadein">
      <h2 className="m-0 mb-4 text-[18px] font-bold tracking-tight">{t("user_model")} · {name}</h2>

      {/* dialectic query box */}
      <div className="card-surface mb-4 p-3.5">
        <div className="text-[var(--dim2)] text-[11px] uppercase tracking-[.7px] mb-2.5">{t("ask_btn")}</div>
        <div className="flex gap-2">
          <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)}
            onKeyDown={e => e.key === "Enter" && ask()}
            placeholder={t("ask_about_user_ph")}
            className="flex-1 bg-[var(--panel2)] border border-[var(--line)] rounded-[9px] px-3 py-2 text-[13px] text-[var(--txt)] outline-none focus:border-[var(--accent)]/60" />
          <button onClick={ask} disabled={asking || !q.trim()}
            className="px-3.5 py-2 rounded-[9px] bg-[var(--accent)] text-white text-[12.5px] font-medium disabled:opacity-40 flex items-center gap-1.5">
            <Send size={13} /> {asking ? t("asking") : t("ask_btn")}
          </button>
        </div>
        {answer && (
          <Markdown text={answer} className="mt-3 text-[13px] text-[var(--txt)] leading-relaxed border-t border-[var(--line)] pt-3" />
        )}
      </div>

      {/* profile */}
      {profile ? (
        <Markdown text={profile} className="card-surface p-[18px] text-[var(--txt)] text-[13.5px] leading-[1.7]" />
      ) : (
        <div className="text-[var(--dim)] text-center py-12">{t("no_user_model")}</div>
      )}
    </div>
  );
}
