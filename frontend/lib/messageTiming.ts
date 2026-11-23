export interface PersistedTokenCountTiming {
  duration: number;
  totalOutputTokens: number;
}

export const buildHistoricalMessageTiming = (
  steps: readonly PersistedTokenCountTiming[]
) => {
  const completedSteps = steps.filter(
    (step) => Number.isFinite(step.duration) && step.duration > 0
  );
  if (completedSteps.length === 0) return undefined;

  const totalDuration = completedSteps.reduce(
    (sum, step) => sum + step.duration,
    0
  );
  const tokenCount = completedSteps.at(-1)?.totalOutputTokens ?? 0;

  return {
    streamStartTime: 0,
    totalStreamTime: totalDuration * 1000,
    tokenCount,
    tokensPerSecond: tokenCount > 0 ? tokenCount / totalDuration : undefined,
    totalChunks: 1,
    toolCallCount: 0,
  };
};
