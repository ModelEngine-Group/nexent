// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { REASONING_EFFORT_VALUES } from "@/const/modelConfig";
import type { ReasoningCapability, ReasoningEffort } from "@/types/modelConfig";

/** Presentation eligibility only; never normalize saved or runtime values. */
export function resolveReasoningAvailability(
  capability: ReasoningCapability | undefined,
  hasValueControls = false
): ReasoningCapability["status"] {
  if (capability && capability.status !== "supported") return capability.status;
  const hasToggle =
    capability?.control === "toggle" ||
    capability?.controls?.some((control) => control.type === "toggle");
  // Explicit legacy selector options remain usable without catalog metadata.
  return hasValueControls || hasToggle ? "supported" : "unknown";
}

export function isReasoningEffort(value: unknown): value is ReasoningEffort {
  return (
    typeof value === "string" &&
    REASONING_EFFORT_VALUES.includes(value as ReasoningEffort)
  );
}
