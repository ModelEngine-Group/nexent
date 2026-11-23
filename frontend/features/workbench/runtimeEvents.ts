/** Accept only safe version confirmations, never arbitrary SSE config objects. */
export function notifyWorkbenchConfigResolved(
  content: unknown,
  onVersion?: (version: number) => void
) {
  try {
    const value = typeof content === "string" ? JSON.parse(content) : content;
    if (
      value &&
      value.schema_version === 3 &&
      Number.isSafeInteger(value.config_version) &&
      value.config_version >= 0
    ) {
      onVersion?.(value.config_version);
    }
  } catch {
    // A malformed auxiliary event must not terminate an otherwise valid stream.
  }
}
