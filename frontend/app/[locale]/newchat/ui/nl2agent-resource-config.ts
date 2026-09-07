import type { SkillParam, ToolParam } from "@/types/agentConfig";

export type Nl2AgentResourceParam = ToolParam | SkillParam;

export interface Nl2AgentConfigFieldError {
  field: string;
  message: string;
}

const isMissingValue = (value: unknown): boolean =>
  value === undefined ||
  value === null ||
  value === "" ||
  (Array.isArray(value) && value.length === 0) ||
  (typeof value === "number" && Number.isNaN(value));

export const validateNl2AgentResourceConfig = (
  params: Nl2AgentResourceParam[]
): Nl2AgentConfigFieldError[] => {
  const values = new Map(params.map((param) => [param.name, param.value]));
  return params.flatMap((param) => {
    if (param.depends_on && !values.get(param.depends_on)) return [];
    if (!param.required || !isMissingValue(param.value)) return [];
    return [
      { field: param.name, message: "Required configuration is missing" },
    ];
  });
};

export const nl2AgentParamsToRecord = (
  params: Nl2AgentResourceParam[]
): Record<string, unknown> =>
  Object.fromEntries(params.map((param) => [param.name, param.value]));

export const readApiFieldErrors = (
  details: unknown
): Nl2AgentConfigFieldError[] => {
  if (!details || typeof details !== "object") return [];
  const fieldErrors = (details as { field_errors?: unknown }).field_errors;
  if (!Array.isArray(fieldErrors)) return [];
  return fieldErrors.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const field = (item as { field?: unknown }).field;
    const message = (item as { message?: unknown }).message;
    return typeof field === "string" && typeof message === "string"
      ? [{ field, message }]
      : [];
  });
};
