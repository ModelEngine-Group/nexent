/**
 * Display helpers for the AIDP knowledge base overview.
 *
 * AIDP does not guarantee the shape of every metadata field: `is_private`
 * arrives as boolean, 0/1 or a string depending on the upstream build, and
 * personal capacity only exists for personal knowledge bases. These helpers
 * normalize what was actually returned and mark everything else as unknown,
 * so the UI never fabricates a value (a missing capacity is not 0 and a
 * missing type is not "enterprise").
 */

/** Placeholder used wherever a real value is unavailable. */
export const AIDP_UNKNOWN_VALUE = "—";

export type AidpKbType = "personal" | "enterprise";

/**
 * Normalize the AIDP `is_private` flag.
 *
 * Returns `null` for anything that is not an unambiguous boolean-like value.
 * Nexent group permissions (PRIVATE / READ_ONLY) are a different concept and
 * must never be used to infer this type.
 */
export function normalizeAidpKbType(isPrivate: unknown): AidpKbType | null {
  if (typeof isPrivate === "boolean") {
    return isPrivate ? "personal" : "enterprise";
  }
  if (typeof isPrivate === "number") {
    if (isPrivate === 1) return "personal";
    if (isPrivate === 0) return "enterprise";
    return null;
  }
  if (typeof isPrivate === "string") {
    const normalized = isPrivate.trim().toLowerCase();
    if (["true", "1", "yes", "personal", "private"].includes(normalized)) {
      return "personal";
    }
    if (["false", "0", "no", "enterprise", "public"].includes(normalized)) {
      return "enterprise";
    }
  }
  return null;
}

/**
 * Format a personal knowledge base capacity.
 *
 * AIDP reports `current_cap` in GB and only for personal knowledge bases.
 * Enterprise knowledge bases and responses without the field render as
 * unknown instead of borrowing the personal capacity or summing file sizes.
 */
export function formatAidpCapacity(currentCap: unknown): string {
  if (
    typeof currentCap !== "number" ||
    !Number.isFinite(currentCap) ||
    currentCap < 0
  ) {
    return AIDP_UNKNOWN_VALUE;
  }
  return `${currentCap} GB`;
}

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

/** Format the graph tag for the overview: enabled, disabled or unknown. */
export function formatAidpBooleanFlag(value: unknown): boolean | null {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (value === 1) return true;
    if (value === 0) return false;
    return null;
  }
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (["true", "1"].includes(normalized)) return true;
    if (["false", "0"].includes(normalized)) return false;
  }
  return null;
}
