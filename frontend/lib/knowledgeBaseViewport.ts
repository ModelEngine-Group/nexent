export const calculateKnowledgeBaseInitialLimit = (
  containerHeight: number,
  averageRowHeight: number,
  maxLimit = 100
): number => {
  if (containerHeight <= 0 || averageRowHeight <= 0) return 1;
  return Math.min(
    maxLimit,
    Math.max(1, Math.ceil(containerHeight / averageRowHeight))
  );
};

export const createKnowledgeBaseFilterKey = (
  keyword: string,
  sources: readonly string[],
  models: readonly string[]
): string => JSON.stringify([keyword, sources, models]);
