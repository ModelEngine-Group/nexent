import { Alert, AutoComplete, Button, Input, Tag, Tooltip } from "antd";
import { useTranslation } from "react-i18next";

import type { CapacitySuggestion } from "@/types/modelConfig";

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
  /**
   * Hide the tokenizer_family input. Used by provider-level "modify config"
   * bulk-apply mode where one value would be forced onto N models with
   * different tokenizer families -- almost always wrong, so we drop the
   * field rather than encourage misuse.
   */
  hideTokenizer?: boolean;
  suggestion?: CapacitySuggestion | null;
  onUseSuggestion?: () => void;
  suggestionLoading?: boolean;
  /**
   * Numeric value from the deprecated `max_tokens` column on the model record.
   * When set AND the user-visible maxOutputTokens input is empty, the panel
   * surfaces a prompt with the value and an "Apply" button -- instead of
   * silently writing it into the form. Independent from the suggest-capacity
   * flow.
   */
  legacyMaxTokensCandidate?: number;
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
  const maxInputTokens = toOptionalPositiveInt(value.maxInputTokens);
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
    contextWindowTokens !== undefined &&
    maxInputTokens !== undefined &&
    maxInputTokens > contextWindowTokens
  ) {
    return "model.dialog.capacity.error.inputExceedsWindow";
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
  /** Legacy alias — surfaced via `legacyMaxTokensCandidate` prompt instead of being
   *  silently written into the form. See ModelCapacityFields. */
  maxTokens?: number;
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

export const capacityFormFromSuggestion = (
  suggestion: CapacitySuggestion | null | undefined
): Partial<ModelCapacityFormState> => {
  const fields = suggestion?.suggestions;
  if (!fields) return {};
  return {
    contextWindowTokens: fields.contextWindowTokens?.toString() || "",
    maxInputTokens: fields.maxInputTokens?.toString() || "",
    maxOutputTokens: fields.maxOutputTokens?.toString() || "",
    defaultOutputReserveTokens:
      fields.defaultOutputReserveTokens?.toString() || "",
    tokenizerFamily: fields.tokenizerFamily || "",
  };
};

export const ModelCapacityFields = ({
  value,
  onChange,
  validationError,
  capacitySource,
  capabilityProfileVersion,
  showDeprecatedMaxTokensWarning,
  formMode = "edit",
  requiredFields = [],
  hideTokenizer = false,
  suggestion,
  onUseSuggestion,
  suggestionLoading = false,
  legacyMaxTokensCandidate,
}: ModelCapacityFieldsProps) => {
  const { t } = useTranslation();

  // Show the actionable legacy-value prompt only while the input is still
  // empty -- once the user applies (or types their own value), the prompt
  // disappears so we don't keep nagging.
  const showLegacyMaxTokensPrompt =
    legacyMaxTokensCandidate !== undefined &&
    legacyMaxTokensCandidate > 0 &&
    value.maxOutputTokens.trim() === "";

  const source = capacitySource || "";
  const sourceColor = SOURCE_COLORS[source] || "default";
  const hasValues = hasCapacityValues(value);
  const hasSuggestion = Boolean(suggestion?.suggestions);
  const requiredSet = new Set<keyof ModelCapacityFormState>(requiredFields);
  const isAddMode = formMode === "add";

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
        {requiredSet.has(field) && <span className="text-red-500 ml-1">*</span>}
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

      {showLegacyMaxTokensPrompt ? (
        <Alert
          type="warning"
          showIcon
          message={t("model.dialog.capacity.legacyMaxTokensDetected", {
            value: legacyMaxTokensCandidate,
            defaultValue: `Detected legacy max_tokens = ${legacyMaxTokensCandidate}. Apply it as max_output_tokens?`,
          })}
          action={
            <Button
              size="small"
              type="primary"
              onClick={() =>
                onChange(
                  "maxOutputTokens",
                  String(legacyMaxTokensCandidate)
                )
              }
            >
              {t("model.dialog.capacity.legacyMaxTokens.apply", {
                defaultValue: "Apply",
              })}
            </Button>
          }
        />
      ) : showDeprecatedMaxTokensWarning ? (
        <Alert
          type="warning"
          showIcon
          message={t("model.dialog.capacity.deprecatedMaxTokens")}
        />
      ) : null}

      {suggestion && (
        <Alert
          type={hasSuggestion ? "success" : "info"}
          showIcon
          message={
            hasSuggestion
              ? t("model.dialog.capacity.suggestion.found")
              : t("model.dialog.capacity.suggestion.notFound")
          }
          description={
            <div className="space-y-2">
              <div className="text-xs">
                {suggestion.matchExplanation ||
                  t("model.dialog.capacity.suggestion.noExplanation")}
              </div>
              {hasSuggestion && (
                <div className="flex flex-wrap items-center gap-2">
                  {suggestion.matchKind && (
                    <Tag>
                      {t(
                        `model.dialog.capacity.suggestion.match.${suggestion.matchKind}`,
                        { defaultValue: suggestion.matchKind }
                      )}
                    </Tag>
                  )}
                  {suggestion.matchConfidence && (
                    <Tag color="blue">
                      {t(
                        `model.dialog.capacity.suggestion.confidence.${suggestion.matchConfidence}`,
                        { defaultValue: suggestion.matchConfidence }
                      )}
                    </Tag>
                  )}
                  {suggestion.canonicalModelName && (
                    <Tag color="green">{suggestion.canonicalModelName}</Tag>
                  )}
                  {suggestion.suggestedProvider && (
                    <Tag color="purple">{suggestion.suggestedProvider}</Tag>
                  )}
                  {onUseSuggestion && (
                    <Button
                      size="small"
                      type="primary"
                      loading={suggestionLoading}
                      onClick={onUseSuggestion}
                    >
                      {t("model.dialog.capacity.suggestion.use")}
                    </Button>
                  )}
                </div>
              )}
            </div>
          }
        />
      )}

      {/* The empty hint suggested "fill later if needed", which contradicts
          required-field asterisks. Only render it when there are no required
          fields, so edit dialogs with required capacity stay self-consistent. */}
      {!source && !hasValues && !isAddMode && requiredSet.size === 0 && (
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
        {/* defaultOutputReserveTokens is rendered in both add and edit modes
            so newly added rows do not silently fall back to the SDK default at
            runtime. Tokenizer renders full-width below in both modes for the
            same consistency reason. */}
        {renderNumberInput(
          "defaultOutputReserveTokens",
          "model.dialog.capacity.defaultOutputReserveTokens",
          "model.dialog.capacity.defaultOutputReserveTokens.tooltip"
        )}
      </div>

      {!hideTokenizer && (
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
            onChange={(nextValue) =>
              onChange("tokenizerFamily", nextValue || "")
            }
            options={TOKENIZER_FAMILY_OPTIONS.map((item) => ({
              label: item,
              value: item,
            }))}
            style={{ width: "100%" }}
          />
        </div>
      )}

      {validationError && (
        <Alert type="error" showIcon message={t(validationError)} />
      )}
    </div>
  );

  // Both add and edit modes render as a flat panel. Required-field
  // asterisks (context_window, max_output_tokens) must be unmissable, and
  // hiding the controls behind a Collapse hides those asterisks.
  return <div className="space-y-2">{content}</div>;
};
