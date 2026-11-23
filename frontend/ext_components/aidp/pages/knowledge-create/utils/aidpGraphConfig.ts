import type { AidpModelOption } from "@/ext_components/aidp/pages/knowledge-create/types";
import type { AidpGraphTemplate } from "@/ext_components/aidp/shared/types/graph";

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
