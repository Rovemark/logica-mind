// Numbered pagination: ‹ 1 … 4 5 6 … 20 ›
export default function Pager({ page, pages, onPage }: { page: number; pages: number; onPage: (p: number) => void }) {
  if (pages <= 1) return null;
  const list = pageNumbers(page, pages);
  const btn = "min-w-[30px] h-[30px] px-2 grid place-items-center rounded-lg border text-[12.5px] tabular-nums transition";
  return (
    <div className="flex items-center justify-center gap-1 mt-5 flex-wrap">
      <button disabled={page <= 1} onClick={() => onPage(page - 1)}
        className={`${btn} border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)] disabled:opacity-30 disabled:cursor-not-allowed`}>‹</button>
      {list.map((n, i) => n < 0
        ? <span key={i} className="px-1 text-[var(--dim2)]">…</span>
        : <button key={i} onClick={() => onPage(n)}
            className={`${btn} ${n === page ? "bg-[var(--panel2)] text-[var(--txt)] border-[var(--line)]"
              : "border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)]"}`}>{n}</button>)}
      <button disabled={page >= pages} onClick={() => onPage(page + 1)}
        className={`${btn} border-[var(--line)] text-[var(--dim)] hover:text-[var(--txt)] disabled:opacity-30 disabled:cursor-not-allowed`}>›</button>
    </div>
  );
}

// 1 … (p-1) p (p+1) … last  — negative entries mark an ellipsis gap
function pageNumbers(page: number, pages: number): number[] {
  const keep = new Set([1, pages, page, page - 1, page + 1]);
  const arr = [...keep].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
  const out: number[] = [];
  let prev = 0;
  for (const n of arr) { if (n - prev > 1) out.push(-1); out.push(n); prev = n; }
  return out;
}

// helper: clamp + total pages
export function paginate<T>(items: T[], page: number, size: number) {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const p = Math.min(Math.max(1, page), pages);
  return { pages, page: p, slice: items.slice((p - 1) * size, p * size) };
}
