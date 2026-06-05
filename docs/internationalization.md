# Internationalization (i18n)

The dashboard ships fully translated into **12 languages**, so the people using your agent's memory read it in their own language — not just the developer who installed it.

## Supported languages

| Code | Language | Script | Direction |
|---|---|---|---|
| `en` | English | Latin | LTR (default) |
| `pt` | Português | Latin | LTR |
| `es` | Español | Latin | LTR |
| `fr` | Français | Latin | LTR |
| `de` | Deutsch | Latin | LTR |
| `id` | Bahasa Indonesia | Latin | LTR |
| `ru` | Русский | Cyrillic | LTR |
| `zh` | 中文 | Han | LTR |
| `ja` | 日本語 | Kana/Kanji | LTR |
| `hi` | हिन्दी | Devanagari | LTR |
| `bn` | বাংলা | Bengali | LTR |
| `ar` | العربية | Arabic | **RTL** |

Together these cover the large majority of the world's internet and developer population. Switch language (and theme) from **Settings**; the choice is remembered in the browser.

## What's translated

- **Every UI string** — all ~420 keys, with full parity across all 12 languages (a missing key, if any, falls back to English).
- **Contextual help** — the `?` on every page, including the multi-paragraph guides.
- **Hover tooltips** — every graph control.
- **Graph relationship labels** — predicates like `works_at` / `part_of` render as natural localized phrases (e.g. 工作于, trabalha em, trabaja en). A small controlled vocabulary is localized; any custom predicate gracefully prettifies (`abc_def` → "abc def"). This is **display-only** — the stored predicate never changes.

## Right-to-left (Arabic)

For Arabic the entire layout mirrors: `<html dir="rtl">` flips the chrome (the sidebar moves to the right, text right-aligns, reading order reverses) — exactly what a native Arabic speaker expects. The knowledge-graph canvas itself is spatial data, so it isn't mirrored. `<html lang>` is set for every language for accessibility and correct font shaping.

## How it works

i18n is a tiny, dependency-free layer (`logica_mind/web/app/src/i18n.tsx`):

- `STR: Record<Lang, Record<string, string>>` holds every language's dictionary.
- `t("key", vars?)` looks up the active language, falls back to English for any missing key, and interpolates `{placeholders}`.
- The active language lives in a React context and persists to `localStorage`.

There are **no runtime translation calls** — every string is shipped in the bundle, so the dashboard stays offline-first and fast.

## Adding a language

1. Add the code to the `Lang` union and the `LANGS` array (with its native label) in `i18n.tsx`.
2. Add a block to `STR` with the same keys as `en`, translated.
3. If the script is right-to-left, it's already handled — `dir="rtl"` is applied for `ar`; add your code to that check.

Key **parity** matters: every language must define every key. A quick check:

```js
const langs = Object.keys(STR);
const base = Object.keys(STR.en);
for (const l of langs) {
  const missing = base.filter((k) => !(k in STR[l]));
  if (missing.length) console.warn(l, "missing", missing);
}
```

## See also

- [Dashboard](./dashboard.md) — the full UI tour (theme + language live in Settings).
- [Graph intelligence](./graph-intelligence.md) — where the localized relationship labels show up.
