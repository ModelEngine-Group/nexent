const ERROR_MARKER_PATTERN = /\b[A-Za-z_][\w.]*(?:Error|Exception):\s/g;

/**
 * Keeps recoverable warnings concise by focusing on the final exception in a
 * nested traceback. The original event content remains unchanged.
 */
export function formatWarningText(value: string): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  let finalErrorIndex = -1;

  for (const match of normalized.matchAll(ERROR_MARKER_PATTERN)) {
    finalErrorIndex = match.index;
  }

  return finalErrorIndex >= 0
    ? normalized.slice(finalErrorIndex)
    : normalized;
}
