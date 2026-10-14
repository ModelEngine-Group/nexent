type RunConfig = { readonly custom?: Record<string, unknown> };

/** Appended card replies bypass the composer, so carry its runtime context explicitly. */
export function nl2AgentCardRunConfig(
  composerRunConfig: RunConfig,
  agentId: number
): RunConfig {
  return {
    ...composerRunConfig,
    custom: {
      ...composerRunConfig.custom,
      runtimeMode: "nl2agent",
      agentId,
    },
  };
}
