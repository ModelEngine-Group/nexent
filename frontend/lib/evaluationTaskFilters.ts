const isIntegerId = (value: unknown): value is number =>
  typeof value === "number" && Number.isInteger(value);

const uniqueIntegerIds = (values: unknown): number[] => {
  if (!Array.isArray(values) || values.some((value) => !isIntegerId(value))) {
    return [];
  }
  return [...new Set(values)];
};

export const parseEvaluationTaskAgentIds = (value: string | null): number[] => {
  if (!value) return [];

  try {
    return uniqueIntegerIds(JSON.parse(value));
  } catch {
    return [];
  }
};

export const buildEvaluationTaskQuery = (agentIds: number[]): string => {
  const params = new URLSearchParams({ limit: "0" });
  const normalizedAgentIds = uniqueIntegerIds(agentIds);
  if (normalizedAgentIds.length > 0) {
    params.set("agent_ids", JSON.stringify(normalizedAgentIds));
  }
  return params.toString();
};

export const shouldShowCreatedEvaluationTask = (
  selectedAgentIds: number[],
  createdAgentId: number
): boolean => {
  const normalizedAgentIds = uniqueIntegerIds(selectedAgentIds);
  return (
    normalizedAgentIds.length === 0 ||
    normalizedAgentIds.includes(createdAgentId)
  );
};
