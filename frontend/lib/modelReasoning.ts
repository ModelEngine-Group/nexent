import { REASONING_EFFORT_VALUES } from "@/const/modelConfig";
import type { ReasoningEffort } from "@/types/modelConfig";

export function isReasoningEffort(value: unknown): value is ReasoningEffort {
  return (
    typeof value === "string" &&
    REASONING_EFFORT_VALUES.includes(value as ReasoningEffort)
  );
}
