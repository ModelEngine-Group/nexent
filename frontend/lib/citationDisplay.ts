// Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

interface CitationIdentity {
  citeIndex?: number;
  toolSign?: string;
}

interface CitationTextPart {
  type?: string;
  text?: unknown;
}

export function getCitationKey(item: CitationIdentity): string | undefined {
  if (!Number.isFinite(item.citeIndex)) return undefined;
  const toolSign = item.toolSign?.trim().toLowerCase();
  return toolSign ? `${toolSign}${item.citeIndex}` : String(item.citeIndex);
}

/** Number cited sources by first appearance, then append uncited results. */
export function buildCitationDisplayIndexMap(
  content: readonly CitationTextPart[],
  sources: readonly CitationIdentity[] = []
): Map<string, number> {
  const sourceKeys = new Set<string>();
  const legacyKeys = new Map<number, string>();
  for (const source of sources) {
    const key = getCitationKey(source);
    if (key === undefined) continue;
    sourceKeys.add(key);
    if (!legacyKeys.has(source.citeIndex!)) {
      legacyKeys.set(source.citeIndex!, key);
    }
  }

  const displayIndices = new Map<string, number>();
  let nextIndex = 1;
  for (const part of content) {
    if (part.type !== "text" || typeof part.text !== "string") continue;
    for (const match of part.text.matchAll(/\[\[([^\]]+)\]\]/g)) {
      const markerKey = match[1].trim().toLowerCase();
      // Numeric legacy markers resolve to the same source as citation clicks.
      const sourceKey = sourceKeys.has(markerKey)
        ? markerKey
        : /^\d+$/.test(markerKey)
          ? (legacyKeys.get(Number(markerKey)) ?? markerKey)
          : markerKey;
      if (!displayIndices.has(sourceKey)) {
        displayIndices.set(sourceKey, nextIndex++);
      }
      displayIndices.set(markerKey, displayIndices.get(sourceKey)!);
    }
  }
  for (const key of sourceKeys) {
    if (!displayIndices.has(key)) displayIndices.set(key, nextIndex++);
  }
  return displayIndices;
}

/** Add presentation numbers without changing the original citation identity. */
export function withCitationDisplayIndices<T extends CitationIdentity>(
  sources: readonly T[],
  displayIndices: ReadonlyMap<string, number>
): Array<T & { displayIndex?: number }> {
  return sources.map((source) => {
    const key = getCitationKey(source);
    return {
      ...source,
      displayIndex: key === undefined ? undefined : displayIndices.get(key),
    };
  });
}
