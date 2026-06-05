// Display label for a relationship predicate. Predicates are DATA (the demo
// seeds English ones; a real graph gets whatever the extractor coins), so we
// localize a controlled vocabulary of common ones via i18n (pred_* keys) and
// gracefully prettify anything unknown (works_at → "works at"). Display-only —
// the stored predicate never changes.
export function predLabel(predicate: string | undefined | null, t: (k: any) => string): string {
  if (!predicate) return "";
  const key = "pred_" + predicate.toLowerCase().trim().replace(/\s+/g, "_");
  const tr = t(key);
  return tr === key ? predicate.replace(/_/g, " ") : tr;   // t() returns the key when missing
}
