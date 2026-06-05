// Life/work "areas" — the four dimension groups, with their colour language.
// Dimension ids carry their group in a prefix (biz_/project_/org_); personal
// dimensions are unprefixed. Kept in one place so the Profile, the memory cards
// and the knowledge graph all speak the same colours.

export type Area = "personal" | "project" | "organization" | "business";

export const AREAS: { id: Area; label: string; color: string }[] = [
  { id: "personal", label: "Person", color: "#a78bfa" },
  { id: "project", label: "Projects", color: "#7c9cff" },
  { id: "organization", label: "Organization", color: "#22d3ee" },
  { id: "business", label: "Business", color: "#4ade80" },
];

const BY_ID: Record<Area, { label: string; color: string }> = Object.fromEntries(
  AREAS.map((a) => [a.id, { label: a.label, color: a.color }]),
) as any;

export function dimArea(dim?: string | null): Area {
  if (!dim) return "personal";
  if (dim.startsWith("biz_")) return "business";
  if (dim.startsWith("project_")) return "project";
  if (dim.startsWith("org_")) return "organization";
  return "personal";
}

export const areaColor = (id: Area) => BY_ID[id].color;
export const areaLabel = (id: Area) => BY_ID[id].label;

// colour for a fact's dimension — its life-area colour, or a neutral tint when
// the fact has no dimension yet.
export function dimColor(dim?: string | null): string {
  if (!dim) return "var(--accent2)";
  return BY_ID[dimArea(dim)].color;
}
