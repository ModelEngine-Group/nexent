// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReasoningEffort } from "@/types/modelConfig";
import { isReasoningEffort } from "@/lib/modelReasoning";

export interface RuntimeGenerationOverrides {
  deep_thinking?: boolean;
  thinking_effort?: ReasoningEffort;
  reasoning_budget_tokens?: number;
  temperature?: number;
  top_p?: number;
}

export interface TurnModelControls {
  model_id: number;
  generation_config: RuntimeGenerationOverrides;
}

/** Copy canonical runtime intent without introducing defaults or mutable references. */
export function snapshotTurnModelControls(
  modelId: string | number,
  generation: RuntimeGenerationOverrides
): TurnModelControls {
  const id = Number(modelId);
  if (!Number.isSafeInteger(id) || id <= 0)
    throw new Error("model_not_available");
  for (const [key, max] of [
    ["temperature", 2],
    ["top_p", 1],
  ] as const) {
    const value = generation[key];
    if (value != null && (!Number.isFinite(value) || value < 0 || value > max))
      throw new Error("model_controls_invalid");
  }
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
      ...(generation.temperature != null
        ? { temperature: generation.temperature }
        : {}),
      ...(generation.top_p != null ? { top_p: generation.top_p } : {}),
    },
  };
}
