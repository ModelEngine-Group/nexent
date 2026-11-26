/** Placeholder used wherever a real value is unavailable. */
export const AIDP_UNKNOWN_VALUE = "—";

/** Format the confirmed document count returned by the backend. */
export function formatAidpDocumentCount(count: unknown): string {
  if (typeof count !== "number" || !Number.isFinite(count)) {
    return AIDP_UNKNOWN_VALUE;
  }
  return String(count);
}

/** Format the creator display name; a raw user id is not a name. */
export function formatAidpCreator(name: unknown): string {
  return typeof name === "string" && name.trim() ? name.trim() : "--";
}
