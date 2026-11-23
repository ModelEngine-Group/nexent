/**
 * Shared helpers for highlighting retrieval citation terms inside source
 * chunks. Used by both the legacy /chat right panel and the /newchat sources
 * panel so the two views highlight the same way.
 */

export const escapeRegExp = (value: string) =>
  value.replace(/[.*+?^${}()|[\]\\]/g, String.raw`\$&`);

export const normalizeForHighlight = (value: string) =>
  value.normalize("NFKC").toLocaleLowerCase();

/** Merge candidate terms, drop substrings of a kept term, and cap the list. */
export const mergeHighlightTerms = (...groups: string[][]): string[] =>
  Array.from(new Set(groups.flat()))
    .sort((left, right) => right.length - left.length)
    .filter(
      (term, index, terms) =>
        !terms.slice(0, index).some((kept) => kept.includes(term)),
    )
    .slice(0, 8);

const collectLiteralTerms = (
  answerContext: string,
  sourceLower: string,
  candidates: Set<string>,
): void => {
  const addIfPresent = (value: string) => {
    const term = value.trim();
    if (term.length >= 2 && sourceLower.includes(normalizeForHighlight(term))) {
      candidates.add(term);
    }
  };

  const patterns = [
    /\b(?:\d{1,3}(?:\.\d{1,3}){3}|\d{2,}(?:[-:.]\d{1,4})*)\b/g,
    /[A-Za-z_][A-Za-z0-9_./-]{2,}/g,
    /\b[A-Za-z]{1,4}\d{1,4}\b/g,
  ];
  for (const pattern of patterns) {
    for (const value of answerContext.match(pattern) || []) {
      addIfPresent(value);
    }
  }
};

const collectChineseTerms = (
  answerContext: string,
  sourceLower: string,
): string[] => {
  const found: string[] = [];
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
        found.push(matched);
        start += matched.length;
      } else {
        start += 1;
      }
    }
  }
  return found;
};

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
  collectLiteralTerms(answerContext, sourceLower, candidates);
  for (const term of collectChineseTerms(answerContext, sourceLower)) {
    candidates.add(term);
  }
  return mergeHighlightTerms(Array.from(candidates));
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
