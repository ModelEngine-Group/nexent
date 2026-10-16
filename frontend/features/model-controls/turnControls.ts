// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReasoningEffort } from "@/types/modelConfig";
import { isReasoningEffort } from "@/lib/modelReasoning";

export interface RuntimeGenerationOverrides {
  deep_thinking?: boolean;
  thinking_effort?: ReasoningEffort;
  reasoning_budget_tokens?: number;
}

export interface TurnModelControls {
  model_id: number;
  generation_config: RuntimeGenerationOverrides;
}

/** Whitelist runtime controls; frontend sampling levels never cross this boundary. */
export function snapshotTurnModelControls(
  modelId: string | number,
  generation: RuntimeGenerationOverrides
): TurnModelControls {
  const id = Number(modelId);
  if (!Number.isSafeInteger(id) || id <= 0)
    throw new Error("model_not_available");
  return {
    model_id: id,
    generation_config: {
      ...(typeof generation.deep_thinking === "boolean"
        ? { deep_thinking: generation.deep_thinking }
        : {}),
      ...(isReasoningEffort(generation.thinking_effort)
        ? { thinking_effort: generation.thinking_effort }
        : {}),
      ...(Number.isInteger(generation.reasoning_budget_tokens) &&
      (generation.reasoning_budget_tokens ?? -1) >= 0
        ? { reasoning_budget_tokens: generation.reasoning_budget_tokens }
        : {}),
    },
  };
}
