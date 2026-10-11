/** Placeholder used wherever a real value is unavailable. */
export const AIDP_UNKNOWN_VALUE = "—";

/**
 * Format the document count.
 *
 * `documentCountReliable` is false when the backend could not confirm a real
 * AIDP count; in that case the value stays unknown, because the backend fills
 * a compatibility default that is not a real statistic.
 */
export function formatAidpDocumentCount(
  count: unknown,
  documentCountReliable: unknown
): string {
  if (documentCountReliable === false) return AIDP_UNKNOWN_VALUE;
  if (typeof count !== "number" || !Number.isFinite(count)) {
    return AIDP_UNKNOWN_VALUE;
  }
  return String(count);
}

/** Format the creator display name; a raw user id is not a name. */
export function formatAidpCreator(name: unknown): string {
  return typeof name === "string" && name.trim() ? name.trim() : "--";
}

/** Format an ISO timestamp, falling back to the unknown placeholder. */
export function formatAidpDateTime(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) return AIDP_UNKNOWN_VALUE;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return AIDP_UNKNOWN_VALUE;
  return parsed.toLocaleDateString();
}
