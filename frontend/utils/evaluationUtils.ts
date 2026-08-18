/** Shared evaluation helpers — used across list, detail, and report views. */

/** Parse a score value from any storage format into a flat name→number map. */
export function parseScore(v: unknown): Record<string, number> {
  if (!v) return {};
  if (typeof v === "number") return { Score: v };
  if (typeof v === "string") {
    try {
      return JSON.parse(v);
    } catch {
      return {};
    }
  }
  if (typeof v === "object") return v as Record<string, number>;
  return {};
}

/** Format a score map into a compact one-line summary like "Name1:0.85 / Name2:0.72". */
export function formatScoreSummary(scores: Record<string, number>): string {
  return Object.entries(scores)
    .map(([k, val]) => `${k}:${val.toFixed(2)}`)
    .join(" / ");
}
