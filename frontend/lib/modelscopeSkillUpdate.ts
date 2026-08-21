export function parseModelScopeTimestamp(
  value: string | null | undefined
): number | null {
  if (!value) return null;
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? null : timestamp;
}

export function shouldShowModelScopeUpdate(
  localVersionUpdateTime: string | null | undefined,
  upstreamLastModified: string | null | undefined
): boolean {
  const localTimestamp = parseModelScopeTimestamp(localVersionUpdateTime);
  const upstreamTimestamp = parseModelScopeTimestamp(upstreamLastModified);
  return (
    localTimestamp !== null &&
    upstreamTimestamp !== null &&
    localTimestamp < upstreamTimestamp
  );
}
