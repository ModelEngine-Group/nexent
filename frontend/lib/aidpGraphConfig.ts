import type { AidpGraphTemplate, AidpModelOption } from "@/types/aidpGraph";

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
    throw new Error("Incomplete AIDP graph configuration template");
  // Reject invalid constraints before they reach form validation.
  data.value.forEach((p) => new RegExp(p.regexp, "u"));
  return data;
}

export function graphParameter(
  data: AidpGraphTemplate | undefined,
  key: string
) {
  return data?.value.find((parameter) => parameter.param_key === key);
}

export function graphChoices(
  data: AidpGraphTemplate | undefined,
  key: string
): string[] {
  const parameter = graphParameter(data, key);
  const match = parameter?.regexp.match(/^\^\(([^()]+)\)\$$/);
  return match ? match[1].split("|") : parameter ? [parameter.param_value] : [];
}

export function graphPrompt(
  data: AidpGraphTemplate | undefined,
  domain: string
): string {
  const parameter = graphParameter(data, "prompt_text");
  return parameter?.template?.[domain] ?? parameter?.param_value ?? "";
}

export function modelOptions(
  models: { model_name: string; display_name?: string; model_type?: string }[],
  type: string
): AidpModelOption[] {
  return models
    .filter((m) => m.model_type === type && m.model_name)
    .map((m) => ({
      value: m.model_name,
      label: m.display_name || m.model_name,
    }));
}

/** Normalize both the verified Chinese values and older detail responses. */
export function graphBoolean(value: unknown): boolean | undefined {
  if (value === true || value === "是" || value === "true" || value === "yes")
    return true;
  if (value === false || value === "否" || value === "false" || value === "no")
    return false;
  return undefined;
}
