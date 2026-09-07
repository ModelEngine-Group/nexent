export interface CapacityFormValue {
  contextWindowTokens: string;
  maxInputTokens: string;
  maxOutputTokens: string;
  defaultOutputReserveTokens: string;
  tokenizerFamily: string;
}

const CAPACITY_KEYS: Array<keyof CapacityFormValue> = [
  "contextWindowTokens",
  "maxInputTokens",
  "maxOutputTokens",
  "defaultOutputReserveTokens",
  "tokenizerFamily",
];

const toOptionalPositiveInt = (raw: string): number | undefined => {
  const trimmed = raw.trim();
  if (!/^[1-9]\d*$/.test(trimmed)) return undefined;
  return Number.parseInt(trimmed, 10);
};

export const hasCapacityInput = (value: CapacityFormValue): boolean =>
  CAPACITY_KEYS.some((key) => value[key].trim() !== "");

export const buildCamelCapacityPayload = (value: CapacityFormValue) => {
  if (!hasCapacityInput(value)) return {};
  return {
    contextWindowTokens: toOptionalPositiveInt(value.contextWindowTokens),
    maxOutputTokens: toOptionalPositiveInt(value.maxOutputTokens),
    capacitySource: "operator" as const,
  };
};

export const buildSnakeCapacityPayload = (value: CapacityFormValue) => {
  if (!hasCapacityInput(value)) return {};
  return {
    context_window_tokens: toOptionalPositiveInt(value.contextWindowTokens),
    max_output_tokens: toOptionalPositiveInt(value.maxOutputTokens),
    capacity_source: "operator" as const,
  };
};
