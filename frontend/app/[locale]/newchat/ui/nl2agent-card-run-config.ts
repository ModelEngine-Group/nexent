// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

type RunConfig = { readonly custom?: Record<string, unknown> };

/** Appended card replies bypass the composer, so carry its runtime context explicitly. */
export function nl2AgentCardRunConfig(
  composerRunConfig: RunConfig,
  agentId: number,
  callbacks?: { onAccepted?: () => void; onRejected?: () => void }
): RunConfig {
  const custom = composerRunConfig.custom;
  return {
    ...composerRunConfig,
    custom: {
      ...composerRunConfig.custom,
      runtimeMode: "nl2agent",
      agentId,
      ...(callbacks
        ? {
            onRunStarted: () => {
              if (typeof custom?.onRunStarted === "function")
                custom.onRunStarted();
              callbacks.onAccepted?.();
            },
            onRunRejected: (...args: unknown[]) => {
              if (typeof custom?.onRunRejected === "function")
                custom.onRunRejected(...args);
              callbacks.onRejected?.();
            },
          }
        : {}),
    },
  };
}
