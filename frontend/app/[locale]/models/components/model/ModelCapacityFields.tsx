import { Alert, AutoComplete, Input, Tag, Tooltip } from "antd";
import { useTranslation } from "react-i18next";

export type CapacitySource =
  | "operator"
  | "profile"
  | "provider_candidate"
  | "legacy"
  | "unknown"
  | string;

export interface ModelCapacityFormState {
  contextWindowTokens: string;
  maxInputTokens: string;
  maxOutputTokens: string;
  defaultOutputReserveTokens: string;
  tokenizerFamily: string;
}

interface ModelCapacityFieldsProps {
  value: ModelCapacityFormState;
  onChange: (field: keyof ModelCapacityFormState, value: string) => void;
  validationError?: string | null;
  capacitySource?: CapacitySource | null;
  capabilityProfileVersion?: string | null;
  showDeprecatedMaxTokensWarning?: boolean;
}

const TOKENIZER_FAMILY_OPTIONS = [
  "o200k_base",
  "qwen",
  "chatglm",
  "deepseek",
  "moonshot",
];

const SOURCE_COLORS: Record<string, string> = {
  operator: "blue",
  profile: "green",
  provider_candidate: "gold",
  legacy: "orange",
  unknown: "default",
};

export const emptyCapacityForm: ModelCapacityFormState = {
  contextWindowTokens: "",
  maxInputTokens: "",
  maxOutputTokens: "",
  defaultOutputReserveTokens: "",
  tokenizerFamily: "",
};

export const capacityFieldKeys: Array<keyof ModelCapacityFormState> = [
  "contextWindowTokens",
  "maxInputTokens",
  "maxOutputTokens",
  "defaultOutputReserveTokens",
  "tokenizerFamily",
];

const toOptionalPositiveInt = (value: string): number | undefined => {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  if (!/^[1-9]\d*$/.test(trimmed)) return undefined;
  return Number.parseInt(trimmed, 10);
};

export const isPositiveIntegerOrEmpty = (value: string): boolean =>
  value.trim() === "" || /^[1-9]\d*$/.test(value.trim());

export const validateCapacityForm = (
  value: ModelCapacityFormState
): string | null => {
  const numericValues = [
    value.contextWindowTokens,
    value.maxInputTokens,
    value.maxOutputTokens,
    value.defaultOutputReserveTokens,
  ];
  if (!numericValues.every(isPositiveIntegerOrEmpty)) {
    return "model.dialog.capacity.error.positiveInteger";
  }

  const contextWindowTokens = toOptionalPositiveInt(value.contextWindowTokens);
  const maxOutputTokens = toOptionalPositiveInt(value.maxOutputTokens);
  const defaultOutputReserveTokens = toOptionalPositiveInt(
    value.defaultOutputReserveTokens
  );

  if (
    contextWindowTokens !== undefined &&
    maxOutputTokens !== undefined &&
    maxOutputTokens > contextWindowTokens
  ) {
    return "model.dialog.capacity.error.outputExceedsWindow";
  }

  if (
    maxOutputTokens !== undefined &&
    defaultOutputReserveTokens !== undefined &&
    defaultOutputReserveTokens > maxOutputTokens
  ) {
    return "model.dialog.capacity.error.reserveExceedsOutput";
  }

  return null;
};

export const hasCapacityValues = (value: ModelCapacityFormState): boolean =>
  capacityFieldKeys.some((key) => value[key].trim() !== "");

export const buildCapacityPayload = (value: ModelCapacityFormState) => {
  if (!hasCapacityValues(value)) return {};
  return {
    contextWindowTokens: toOptionalPositiveInt(value.contextWindowTokens),
    maxInputTokens: toOptionalPositiveInt(value.maxInputTokens),
    maxOutputTokens: toOptionalPositiveInt(value.maxOutputTokens),
    defaultOutputReserveTokens: toOptionalPositiveInt(
      value.defaultOutputReserveTokens
    ),
    tokenizerFamily: value.tokenizerFamily.trim() || undefined,
    capacitySource: "operator",
  };
};

export const capacityFormFromModel = (model: {
  contextWindowTokens?: number;
  maxInputTokens?: number;
  maxOutputTokens?: number;
  defaultOutputReserveTokens?: number;
  tokenizerFamily?: string;
}): ModelCapacityFormState => ({
  contextWindowTokens: model.contextWindowTokens?.toString() || "",
  maxInputTokens: model.maxInputTokens?.toString() || "",
  maxOutputTokens: model.maxOutputTokens?.toString() || "",
  defaultOutputReserveTokens:
    model.defaultOutputReserveTokens?.toString() || "",
  tokenizerFamily: model.tokenizerFamily || "",
});

export const ModelCapacityFields = ({
  value,
  onChange,
  validationError,
  capacitySource,
  capabilityProfileVersion,
  showDeprecatedMaxTokensWarning,
}: ModelCapacityFieldsProps) => {
  const { t } = useTranslation();

  const source = capacitySource || "";
  const sourceColor = SOURCE_COLORS[source] || "default";

  const renderNumberInput = (
    field: keyof ModelCapacityFormState,
    labelKey: string,
    tooltipKey: string
  ) => (
    <div>
      <label className="block mb-1 text-sm font-medium text-gray-700">
        <Tooltip title={t(tooltipKey)}>
          <span>{t(labelKey)}</span>
        </Tooltip>
      </label>
      <Input
        type="number"
        min="1"
        value={value[field]}
        onChange={(event) => onChange(field, event.target.value)}
      />
    </div>
  );

  return (
    <div className="space-y-3">
      {(source || capabilityProfileVersion) && (
        <div className="flex flex-wrap items-center gap-2">
          {source && (
            <Tag color={sourceColor}>
              {t(`model.dialog.capacity.source.${source}`, {
                defaultValue: source,
              })}
            </Tag>
          )}
          {capabilityProfileVersion && (
            <span className="text-xs text-gray-500">
              {capabilityProfileVersion}
            </span>
          )}
        </div>
      )}

      {showDeprecatedMaxTokensWarning && (
        <Alert
          type="warning"
          showIcon
          message={t("model.dialog.capacity.deprecatedMaxTokens")}
        />
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {renderNumberInput(
          "contextWindowTokens",
          "model.dialog.capacity.contextWindowTokens",
          "model.dialog.capacity.contextWindowTokens.tooltip"
        )}
        {renderNumberInput(
          "maxInputTokens",
          "model.dialog.capacity.maxInputTokens",
          "model.dialog.capacity.maxInputTokens.tooltip"
        )}
        {renderNumberInput(
          "maxOutputTokens",
          "model.dialog.capacity.maxOutputTokens",
          "model.dialog.capacity.maxOutputTokens.tooltip"
        )}
        {renderNumberInput(
          "defaultOutputReserveTokens",
          "model.dialog.capacity.defaultOutputReserveTokens",
          "model.dialog.capacity.defaultOutputReserveTokens.tooltip"
        )}
      </div>

      <div>
        <label className="block mb-1 text-sm font-medium text-gray-700">
          <Tooltip title={t("model.dialog.capacity.tokenizerFamily.tooltip")}>
            <span>{t("model.dialog.capacity.tokenizerFamily")}</span>
          </Tooltip>
        </label>
        <AutoComplete
          allowClear
          value={value.tokenizerFamily}
          onChange={(nextValue) => onChange("tokenizerFamily", nextValue || "")}
          options={TOKENIZER_FAMILY_OPTIONS.map((item) => ({
            label: item,
            value: item,
          }))}
          style={{ width: "100%" }}
        />
      </div>

      {validationError && (
        <Alert type="error" showIcon message={t(validationError)} />
      )}
    </div>
  );
};
