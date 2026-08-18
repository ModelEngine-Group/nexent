/**
 * Shared helpers for highlighting retrieval citation terms inside source
 * chunks. Used by both the legacy /chat right panel and the /newchat sources
 * panel so the two views highlight the same way.
 */

export const escapeRegExp = (value: string) =>
  value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export const normalizeForHighlight = (value: string) =>
  value.normalize("NFKC").toLocaleLowerCase();

/**
 * Extract the terms from the cited answer context that also appear in the
 * source chunk, so the chunk card can highlight the overlapping text.
 */
export const extractHighlightTerms = (
  answerContext: string,
  sourceText: string,
): string[] => {
  if (!answerContext || !sourceText) return [];

  const sourceLower = normalizeForHighlight(sourceText);
  const candidates = new Set<string>();
  const addIfPresent = (value: string) => {
    const term = value.trim();
    if (term.length >= 2 && sourceLower.includes(normalizeForHighlight(term))) {
      candidates.add(term);
    }
  };

  for (const value of answerContext.match(
    /\b(?:\d{1,3}(?:\.\d{1,3}){3}|\d{2,}(?:[-:.]\d{1,4})*)\b/g,
  ) || []) {
    addIfPresent(value);
  }
  for (
    const value of answerContext.match(/[A-Za-z_][A-Za-z0-9_./-]{2,}/g) || []
  ) {
    addIfPresent(value);
  }
  for (const value of answerContext.match(/\b[A-Za-z]{1,4}\d{1,4}\b/g) || []) {
    addIfPresent(value);
  }
  for (const phrase of answerContext.match(/[\u4e00-\u9fff]{3,}/g) || []) {
    for (let start = 0; start <= phrase.length - 3; ) {
      let matched = "";
      for (
        let length = Math.min(12, phrase.length - start);
        length >= 3;
        length -= 1
      ) {
        const candidate = phrase.slice(start, start + length);
        if (sourceLower.includes(normalizeForHighlight(candidate))) {
          matched = candidate;
          break;
        }
      }
      if (matched) {
        candidates.add(matched);
        start += matched.length;
      } else {
        start += 1;
      }
    }
  }

  return Array.from(candidates)
    .sort((left, right) => right.length - left.length)
    .filter(
      (term, index, terms) =>
        !terms.slice(0, index).some((kept) => kept.includes(term)),
    )
    .slice(0, 8);
};

/**
 * Split a source chunk into the smallest readable units (sentences or
 * Markdown table rows) so each can be highlighted independently.
 */
export const splitSourceTextIntoSentences = (text: string): string[] =>
  text.split(/(\r?\n)/).flatMap((line) => {
    if (!line || /^\r?\n$/.test(line)) return [line];

    // A Markdown table row is the smallest readable source unit.
    if (/^\s*\|.*\|\s*$/.test(line)) return [line];

    return line.match(/[^。！？!?；;]+[。！？!?；;]?/g) || [line];
  });
