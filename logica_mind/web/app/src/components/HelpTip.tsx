import { useState } from "react";
import { useI18n } from "../i18n";

// A contextual "?" for the current page. Content lives in i18n under `help_<key>`:
// the first line is a title, following lines are paragraphs, and lines starting
// with "• " render as bullets. Explains what every element on the page means.
export default function HelpTip({ k }: { k: string }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const text = t(`help_${k}`);
  if (!text || text === `help_${k}`) return null;   // no help authored → no button
  const lines = text.split("\n").filter((l) => l.length);

  return (
    <div className="relative flex-none">
      <button onClick={() => setOpen((o) => !o)} aria-label="help" title={t("help_word")}
        className={`w-[22px] h-[22px] grid place-items-center rounded-full border text-[12px] font-semibold transition
          ${open ? "border-[var(--accent)] text-[var(--accent)] bg-[var(--panel2)]"
                 : "border-[var(--line)] text-[var(--dim2)] hover:text-[var(--txt)] hover:border-[var(--accent)]"}`}>?</button>
      {open && (
        <>
          <div className="fixed inset-0 z-[70]" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-[30px] z-[71] w-[330px] max-w-[80vw] card-surface p-4 shadow-[var(--shadow)]
            text-[12.5px] text-[var(--dim)] leading-relaxed fadein">
            {lines.map((line, i) =>
              line.startsWith("• ") ? (
                <div key={i} className="flex gap-1.5 mt-1.5">
                  <span className="text-[var(--accent)] flex-none">•</span><span>{line.slice(2)}</span>
                </div>
              ) : (
                <p key={i} className={`m-0 ${i ? "mt-1.5" : ""} ${i === 0 ? "text-[var(--txt)] font-semibold text-[13.5px]" : ""}`}>{line}</p>
              )
            )}
          </div>
        </>
      )}
    </div>
  );
}
