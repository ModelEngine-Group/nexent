import { useEffect, useState } from "react";
import { Alert, AutoComplete, Collapse, Input, Tag, Tooltip } from "antd";
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

export type ModelCapacityFormMode = "add" | "edit";

interface ModelCapacityFieldsProps {
  value: ModelCapacityFormState;
  onChange: (field: keyof ModelCapacityFormState, value: string) => void;
  validationError?: string | null;
  capacitySource?: CapacitySource | null;
  capabilityProfileVersion?: string | null;
  showDeprecatedMaxTokensWarning?: boolean;
  /**
   * 'add' shows a flat panel with the four user-facing fields
   * (context_window, max_input, max_output, tokenizer) and supports required
   * markers. 'edit' shows all five fields inside a collapsible panel. Default 'edit'.
   */
  formMode?: ModelCapacityFormMode;
  /** Field names that should render a red asterisk and be enforced by validation. */
  requiredFields?: Array<keyof ModelCapacityFormState>;
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
  value: ModelCapacityFormState,
  requiredFields: Array<keyof ModelCapacityFormState> = []
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

  for (const field of requiredFields) {
    if (value[field].trim() === "") {
      return "model.dialog.capacity.error.requiredMissing";
    }
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
  const maxOutputTokens = toOptionalPositiveInt(value.maxOutputTokens);
  return {
    contextWindowTokens: toOptionalPositiveInt(value.contextWindowTokens),
    maxInputTokens: toOptionalPositiveInt(value.maxInputTokens),
    maxOutputTokens,
    // Mirror max_output_tokens into the deprecated max_tokens column so
    // legacy readers stay consistent. W1 step 4 makes them aliases server-side;
    // keeping both columns populated avoids a brittle dependency on the
    // Pydantic validator firing on every code path.
    ...(maxOutputTokens !== undefined ? { maxTokens: maxOutputTokens } : {}),
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
  /** Legacy alias — auto-promoted to maxOutputTokens when the new field is empty. */
  maxTokens?: number;
  defaultOutputReserveTokens?: number;
  tokenizerFamily?: string;
}): ModelCapacityFormState => ({
  contextWindowTokens: model.contextWindowTokens?.toString() || "",
  maxInputTokens: model.maxInputTokens?.toString() || "",
  // W1 step 4 deprecates max_tokens. Promote legacy value into the new field
  // for display so the user sees the value and the deprecation warning
  // resolves on save (the saved value lands in max_output_tokens column).
  maxOutputTokens:
    model.maxOutputTokens?.toString() || model.maxTokens?.toString() || "",
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
  formMode = "edit",
  requiredFields = [],
}: ModelCapacityFieldsProps) => {
  const { t } = useTranslation();

  const source = capacitySource || "";
  const sourceColor = SOURCE_COLORS[source] || "default";
  const hasValues = hasCapacityValues(value);
  const requiredSet = new Set<keyof ModelCapacityFormState>(requiredFields);
  const isAddMode = formMode === "add";
  const shouldAutoOpen = Boolean(
    hasValues || source || capabilityProfileVersion || validationError
  );
  const [isOpen, setIsOpen] = useState(shouldAutoOpen);

  useEffect(() => {
    if (shouldAutoOpen) {
      setIsOpen(true);
    }
  }, [shouldAutoOpen]);

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
        {requiredSet.has(field) && (
          <span className="text-red-500 ml-1">*</span>
        )}
      </label>
      <Input
        type="number"
        min="1"
        value={value[field]}
        onChange={(event) => onChange(field, event.target.value)}
      />
    </div>
  );

  const content = (
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

      {!source && !hasValues && !isAddMode && (
        <Alert
          type="info"
          showIcon
          message={t("model.dialog.capacity.emptyHint")}
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
        {!isAddMode &&
          renderNumberInput(
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
          {requiredSet.has("tokenizerFamily") && (
            <span className="text-red-500 ml-1">*</span>
          )}
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

  // In add mode the capacity fields are part of required input; render as a
  // flat labelled section so context_window/max_input red asterisks are
  // unmissable. Edit mode keeps the existing collapsible panel.
  if (isAddMode) {
    return (
      <div className="space-y-2">
        <div>
          <div className="text-sm font-medium text-gray-700">
            {t("model.dialog.capacity.title")}
          </div>
          <div className="text-xs font-normal text-gray-500">
            {t("model.dialog.capacity.description")}
          </div>
        </div>
        {content}
      </div>
    );
  }

  return (
    <Collapse
      ghost
      activeKey={isOpen ? ["capacity"] : []}
      onChange={(keys) => setIsOpen(Array.isArray(keys) && keys.includes("capacity"))}
      items={[
        {
          key: "capacity",
          label: (
            <div>
              <div className="text-sm font-medium text-gray-700">
                {t("model.dialog.capacity.title")}
              </div>
              <div className="text-xs font-normal text-gray-500">
                {source || hasValues
                  ? t("model.dialog.capacity.description")
                  : t("model.dialog.capacity.emptySummary")}
              </div>
            </div>
          ),
          children: content,
        },
      ]}
      className="model-capacity-fields"
    />
  );
};
