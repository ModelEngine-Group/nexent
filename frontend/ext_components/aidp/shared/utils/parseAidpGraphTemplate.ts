import { ApiError } from "@/services/api";
import { ErrorCode } from "@/const/errorCode";
import type { AidpGraphTemplate } from "@/ext_components/aidp/shared/types/graph";

const parameterKeys = [
  "retrieve_subgraph_hop",
  "no_think_mode",
  "prompt_language",
  "domain",
  "prompt_text",
  "synonym_merge_enable",
  "disambiguation_enable",
];

export function parseAidpGraphTemplate(raw: unknown): AidpGraphTemplate {
  const data = raw as AidpGraphTemplate | undefined;
  if (
    !Array.isArray(data?.value) ||
    !parameterKeys.every((key) =>
      data.value.some(
        (p) =>
          p.param_key === key &&
          typeof p.param_value === "string" &&
          typeof p.regexp === "string" &&
          typeof p.is_modifiable === "boolean"
      )
    )
  )
    throw new ApiError(
      ErrorCode.AIDP_RESPONSE_ERROR,
      "Incomplete AIDP graph configuration template"
    );
  // Reject invalid constraints before they reach form validation.
  try {
    data.value.forEach((p) => new RegExp(p.regexp, "u"));
  } catch {
    throw new ApiError(
      ErrorCode.AIDP_RESPONSE_ERROR,
      "Invalid AIDP graph template constraint"
    );
  }
  return data;
}
