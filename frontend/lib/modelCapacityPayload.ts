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
    maxInputTokens: toOptionalPositiveInt(value.maxInputTokens),
    maxOutputTokens: toOptionalPositiveInt(value.maxOutputTokens),
    defaultOutputReserveTokens: toOptionalPositiveInt(
      value.defaultOutputReserveTokens
    ),
    tokenizerFamily: value.tokenizerFamily.trim() || undefined,
    capacitySource: "operator" as const,
  };
};

export const buildSnakeCapacityPayload = (value: CapacityFormValue) => {
  if (!hasCapacityInput(value)) return {};
  return {
    context_window_tokens: toOptionalPositiveInt(value.contextWindowTokens),
    max_input_tokens: toOptionalPositiveInt(value.maxInputTokens),
    max_output_tokens: toOptionalPositiveInt(value.maxOutputTokens),
    default_output_reserve_tokens: toOptionalPositiveInt(
      value.defaultOutputReserveTokens
    ),
    tokenizer_family: value.tokenizerFamily.trim() || undefined,
    capacity_source: "operator" as const,
  };
};
