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
