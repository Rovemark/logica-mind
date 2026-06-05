// Theme: dark (default) / light / auto (follow the browser). Persisted in
// localStorage and applied as data-theme on <html> (the CSS vars do the rest).
export type Theme = "dark" | "light" | "auto";

const KEY = "lm-theme";
const mq = () => window.matchMedia("(prefers-color-scheme: dark)");

export function effective(t: Theme): "dark" | "light" {
  return t === "auto" ? (mq().matches ? "dark" : "light") : t;
}

export function applyTheme(t: Theme) {
  document.documentElement.setAttribute("data-theme", effective(t));
}

export function getTheme(): Theme {
  return (localStorage.getItem(KEY) as Theme) || "dark";
}

export function setTheme(t: Theme) {
  localStorage.setItem(KEY, t);
  applyTheme(t);
}

// call once at startup: apply the stored theme and keep "auto" in sync with the OS
export function initTheme(): Theme {
  const t = getTheme();
  applyTheme(t);
  mq().addEventListener("change", () => { if (getTheme() === "auto") applyTheme("auto"); });
  return t;
}
