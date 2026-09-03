import { Alert, AutoComplete, Button, Input, Space, Tag, Tooltip } from "antd";
import { useTranslation } from "react-i18next";

import type {
  CapacityFieldMetadata,
  CapacitySuggestion,
  ProfileMatchMetadata,
  TokenCountProbeMetadata,
} from "@/types/modelConfig";
import { buildCamelCapacityPayload } from "@/lib/modelCapacityPayload";

// W11 spec L767-790. Common token-count presets surfaced as a fallback
// preset selector when no catalog suggestion populates the field. The
// values mirror MAX_TOKEN_OPTIONS in ModelMaxTokensInput so the two
// surfaces (legacy max_tokens batch input and capacity panel) offer
// the same dropdown choices. Operators can still type a custom value;
// AutoComplete accepts free numeric input.
const CONTEXT_WINDOW_PRESET_OPTIONS = [
  { value: "4096", label: "4K / 4,096" },
  { value: "8192", label: "8K / 8,192" },
  { value: "16384", label: "16K / 16,384" },
  { value: "32768", label: "32K / 32,768" },
  { value: "65536", label: "64K / 65,536" },
  { value: "131072", label: "128K / 131,072" },
  { value: "204800", label: "200K / 204,800" },
  { value: "262144", label: "256K / 262,144" },
  { value: "1048576", label: "1M / 1,048,576" },
];

// Shared by both default_output_reserve_tokens and max_output_tokens. The
// reserve list maps to spec L782-790 verbatim; reusing it for max_output
// gives operators the same dropdown choices they already see for the
// reserve field. Values above 16K (e.g. GPT-4.1's 32K cap, GLM-5.1's
// 131K cap) still work via free-text typing through AutoComplete.
const OUTPUT_RESERVE_PRESET_OPTIONS = [
  { value: "256", label: "256" },
  { value: "512", label: "512" },
  { value: "1024", label: "1K / 1,024" },
  { value: "2048", label: "2K / 2,048" },
  { value: "4096", label: "4K / 4,096" },
  { value: "8192", label: "8K / 8,192" },
  { value: "16384", label: "16K / 16,384" },
];

export type CapacitySource =
  "operator" | "profile" | "provider_candidate" | "legacy" | "unknown" | string;

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
  capacityFieldMetadata?: CapacityFieldMetadata | null;
  canonicalModelId?: string | null;
  tokenizerMatchMetadata?: ProfileMatchMetadata | null;
  tokenCountProbeMetadata?: TokenCountProbeMetadata | null;
  onReviewAutomaticUpdate?: () => void;
  reviewingAutomaticUpdate?: boolean;
  onProbeTokenCount?: () => void;
  probingTokenCount?: boolean;
  /**
   * 'add' shows a flat panel with the four user-facing fields
   * (context_window, max_input, max_output, tokenizer) and supports required
   * markers. 'edit' shows all five fields inside a collapsible panel. Default 'edit'.
   */
  formMode?: ModelCapacityFormMode;
  /** Field names that should render a red asterisk and be enforced by validation. */
  requiredFields?: Array<keyof ModelCapacityFormState>;
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
  /**
   * When true (default), context_window/max_output inputs render gray
   * estimated-value placeholders. Placeholders are never serialized. Pass
   * false in bulk-apply mode where even a visual estimate is misleading.
   */
  applyDefaultsOnEmpty?: boolean;
  /** Currently accepted suggestion, used to detect fuzzy canonicalization mismatch */
  acceptedSuggestion?: CapacitySuggestion | null;
  disabled?: boolean;
}

const SOURCE_COLORS: Record<string, string> = {
  operator: "blue",
  profile: "green",
  provider_candidate: "gold",
  legacy: "orange",
  unknown: "default",
};

// Save-time defaults for the two fields that are no longer required in
// the UI. When the operator leaves the input empty AND the caller opts
// into default substitution, `buildCapacityPayload` writes these values
// to the wire payload. Chosen to mirror the runtime fallbacks already in
// the SDK (`_TOKEN_THRESHOLD_LEGACY_FALLBACK = 32768`,
// `_DEFAULT_REQUESTED_OUTPUT_TOKENS = 4096`), so going from an empty
// input to "the default landed" doesn't change observed runtime behavior.
export const DEFAULT_CONTEXT_WINDOW_TOKENS = 32_768;
export const DEFAULT_MAX_OUTPUT_TOKENS = 4_096;

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
  const numericValues = [value.contextWindowTokens, value.maxOutputTokens];
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

  if (
    contextWindowTokens !== undefined &&
    maxOutputTokens !== undefined &&
    maxOutputTokens >= contextWindowTokens
  ) {
    return "model.dialog.capacity.error.outputExceedsWindow";
  }

  return null;
};

export const hasCapacityValues = (value: ModelCapacityFormState): boolean =>
  capacityFieldKeys.some((key) => value[key].trim() !== "");

export const buildCapacityPayload = (
  value: ModelCapacityFormState,
  _options?: { applyDefaults?: boolean }
) => {
  void _options;
  return buildCamelCapacityPayload(value);
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
  capacityFieldMetadata,
  canonicalModelId,
  tokenizerMatchMetadata,
  tokenCountProbeMetadata,
  onReviewAutomaticUpdate,
  reviewingAutomaticUpdate = false,
  onProbeTokenCount,
  probingTokenCount = false,
  requiredFields = [],
  suggestion,
  onUseSuggestion,
  suggestionLoading = false,
  legacyMaxTokensCandidate,
  applyDefaultsOnEmpty = true,
  acceptedSuggestion,
  disabled = false,
}: ModelCapacityFieldsProps) => {
  const { t } = useTranslation();

  // Legacy max_tokens can mean either thing -- before W1 split capacity,
  // operators sometimes typed the provider context window there
  // (128000, 32768, ...) and sometimes the per-call output cap (4096,
  // 8192, ...). We can't tell from the value alone, so we surface both
  // target fields and let the operator pick. The button order is the
  // only heuristic: values >= LEGACY_CONTEXT_WINDOW_THRESHOLD are
  // far more likely to be context windows (no real model caps output
  // at 32K+ in practice), so the "Apply as Context Window" button leads;
  // below the threshold the "Apply as Max Output" button leads.
  //
  // Each button is independently gated by its target field being empty
  // -- once the operator commits a value to that column we stop nagging
  // about it. When both fields are filled the whole alert hides.
  const LEGACY_CONTEXT_WINDOW_THRESHOLD = 16_384;
  const legacyValuePositive =
    legacyMaxTokensCandidate !== undefined && legacyMaxTokensCandidate > 0;
  const canApplyAsContextWindow =
    legacyValuePositive && value.contextWindowTokens.trim() === "";
  const canApplyAsMaxOutput =
    legacyValuePositive && value.maxOutputTokens.trim() === "";
  const showLegacyMaxTokensPrompt =
    canApplyAsContextWindow || canApplyAsMaxOutput;
  const contextWindowIsRecommended =
    (legacyMaxTokensCandidate ?? 0) >= LEGACY_CONTEXT_WINDOW_THRESHOLD;

  const source = capacitySource || "";
  const sourceColor = SOURCE_COLORS[source] || "default";
  const hasSuggestion = Boolean(suggestion?.suggestions);
  const requiredSet = new Set<keyof ModelCapacityFormState>(requiredFields);

  // Per-field estimates rendered as native input placeholders. They are
  // never serialized unless the operator explicitly enters or selects them.
  const defaultPlaceholders: Partial<
    Record<keyof ModelCapacityFormState, string>
  > = applyDefaultsOnEmpty
    ? {
        contextWindowTokens: DEFAULT_CONTEXT_WINDOW_TOKENS.toString(),
        maxOutputTokens: DEFAULT_MAX_OUTPUT_TOKENS.toString(),
      }
    : {};

  // Per W11 spec L762-765, the context-window and output-reserve fields
  // expose a preset selector when no catalog suggestion is available. The
  // suggestion-set check is per-field: if the suggestion populated this
  // exact field, plain numeric input avoids burying the suggested value
  // behind dropdown chrome. Otherwise show the preset list to help
  // operators avoid typos like "1280000" instead of "128000".
  const suggestionFields = suggestion?.suggestions ?? null;
  const fieldHasSuggestion = (field: keyof ModelCapacityFormState): boolean => {
    if (!suggestionFields) return false;
    const suggested = (suggestionFields as Record<string, unknown>)[field];
    return suggested != null && suggested !== "";
  };

  const renderNumberInput = (
    field: keyof ModelCapacityFormState,
    labelKey: string,
    tooltipKey: string,
    presetOptions?: { value: string; label: string }[]
  ) => {
    const showPreset = presetOptions && !fieldHasSuggestion(field);
    const provenance = capacityFieldMetadata?.fields[field];
    const sourceLabels: Record<string, string> = {
      catalog: "Automatic",
      provider: "Provider",
      operator: "Manual",
      legacy: "Legacy",
      unknown: "Unknown",
    };
    const inputControl = showPreset ? (
      <AutoComplete
        className="w-full"
        value={value[field]}
        options={presetOptions}
        placeholder={defaultPlaceholders[field]}
        onChange={(next) => onChange(field, String(next ?? ""))}
        disabled={disabled}
        filterOption={(input, option) =>
          String(option?.label ?? "")
            .toLowerCase()
            .includes(input.toLowerCase()) ||
          String(option?.value ?? "").includes(input)
        }
      >
        <Input inputMode="numeric" pattern="[0-9]*" disabled={disabled} />
      </AutoComplete>
    ) : (
      <Input
        type="number"
        min="1"
        value={value[field]}
        placeholder={defaultPlaceholders[field]}
        onChange={(event) => onChange(field, event.target.value)}
        disabled={disabled}
      />
    );
    return (
      <div>
        <label className="block mb-1 text-sm font-medium text-gray-700">
          <Tooltip title={t(tooltipKey)}>
            <span>{t(labelKey)}</span>
          </Tooltip>
          {requiredSet.has(field) && (
            <span className="text-red-500 ml-1">*</span>
          )}
          {provenance?.source && (
            <Tag
              className="ml-2"
              color={
                provenance.source === "catalog"
                  ? "green"
                  : provenance.source === "operator"
                    ? "blue"
                    : provenance.source === "provider"
                      ? "gold"
                      : provenance.source === "legacy"
                        ? "orange"
                        : "default"
              }
            >
              {t(`model.dialog.capacity.fieldSource.${provenance.source}`, {
                defaultValue:
                  sourceLabels[provenance.source] || provenance.source,
              })}
            </Tag>
          )}
        </label>
        {inputControl}
      </div>
    );
  };

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

      {(canonicalModelId ||
        tokenizerMatchMetadata ||
        tokenCountProbeMetadata) && (
        <div className="rounded border border-gray-200 bg-gray-50 p-2 text-xs text-gray-600 space-y-1">
          {canonicalModelId && <div>Model identity: {canonicalModelId}</div>}
          {tokenizerMatchMetadata && (
            <div>
              Tokenizer:{" "}
              {tokenizerMatchMetadata.autoApplicable ? "Exact" : "Estimated"}
              {tokenizerMatchMetadata.reason
                ? ` · ${tokenizerMatchMetadata.reason}`
                : ""}
            </div>
          )}
          {tokenCountProbeMetadata && (
            <div>
              Count endpoint: {tokenCountProbeMetadata.status} ·{" "}
              {tokenCountProbeMetadata.reason}
            </div>
          )}
          <Space size={6} wrap>
            {onReviewAutomaticUpdate && (
              <Button
                size="small"
                onClick={onReviewAutomaticUpdate}
                loading={reviewingAutomaticUpdate}
                disabled={disabled}
              >
                Review automatic update
              </Button>
            )}
            {onProbeTokenCount && (
              <Button
                size="small"
                onClick={onProbeTokenCount}
                loading={probingTokenCount}
                disabled={disabled}
              >
                Test token count
              </Button>
            )}
          </Space>
        </div>
      )}

      {showLegacyMaxTokensPrompt ? (
        <Alert
          type="warning"
          showIcon
          title={t("model.dialog.capacity.legacyMaxTokensHint", {
            maxTokens: legacyMaxTokensCandidate,
          })}
          description={
            <Space size={6} wrap className="mt-2">
              {(contextWindowIsRecommended
                ? ["context", "output"]
                : ["output", "context"]
              ).map((target, idx) => {
                if (target === "context" && !canApplyAsContextWindow) {
                  return null;
                }
                if (target === "output" && !canApplyAsMaxOutput) {
                  return null;
                }
                const labelKey =
                  target === "context"
                    ? "model.dialog.capacity.legacyMaxTokens.applyAsContext"
                    : "model.dialog.capacity.legacyMaxTokens.applyAsOutput";
                const fieldName =
                  target === "context"
                    ? "contextWindowTokens"
                    : "maxOutputTokens";
                return (
                  <Button
                    key={target}
                    size="small"
                    type={idx === 0 ? "primary" : "default"}
                    onClick={() =>
                      onChange(fieldName, String(legacyMaxTokensCandidate))
                    }
                    disabled={disabled}
                  >
                    {t(labelKey)}
                  </Button>
                );
              })}
            </Space>
          }
        />
      ) : null}

      {suggestion && (
        <Alert
          type={hasSuggestion ? "success" : "info"}
          showIcon
          title={
            hasSuggestion
              ? t("model.dialog.capacity.suggestion.found")
              : t("model.dialog.capacity.suggestion.notFound")
          }
          description={
            hasSuggestion ? (
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  {suggestion.canonicalModelName && (
                    <span className="font-medium text-sm">
                      {suggestion.canonicalModelName}
                    </span>
                  )}
                  {suggestion.matchKind && (
                    <>
                      <span className="text-gray-300">·</span>
                      <span className="text-xs text-gray-500">
                        {t(
                          `model.dialog.capacity.suggestion.match.${suggestion.matchKind}`,
                          { defaultValue: suggestion.matchKind }
                        )}
                      </span>
                    </>
                  )}
                  {onUseSuggestion && (
                    <Button
                      size="small"
                      type="primary"
                      loading={suggestionLoading}
                      onClick={onUseSuggestion}
                      disabled={disabled}
                    >
                      {t("model.dialog.capacity.suggestion.use")}
                    </Button>
                  )}
                </div>
                {suggestion.matchKind === "catalog_fuzzy" &&
                  (!acceptedSuggestion ||
                    (acceptedSuggestion &&
                      acceptedSuggestion.canonicalModelName !==
                        suggestion.canonicalModelName)) && (
                    <div className="text-xs text-yellow-700">
                      {t("model.dialog.capacity.suggestion.profileMissWarning")}
                    </div>
                  )}
              </div>
            ) : (
              <div className="text-xs">
                {t("model.dialog.capacity.suggestion.notFoundDescription")}
              </div>
            )
          }
        />
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {renderNumberInput(
          "contextWindowTokens",
          "model.dialog.capacity.contextWindowTokens",
          "model.dialog.capacity.contextWindowTokens.tooltip",
          CONTEXT_WINDOW_PRESET_OPTIONS
        )}
        {renderNumberInput(
          "maxOutputTokens",
          "model.dialog.capacity.maxOutputTokens",
          "model.dialog.capacity.maxOutputTokens.tooltip",
          OUTPUT_RESERVE_PRESET_OPTIONS
        )}
      </div>

      {/* tokenizer_family input intentionally not rendered: the field is
          recorded silently (auto-filled by W11 catalog suggestion or
          preserved from existing DB rows) and consumed only by the
          tokenizer_registry — operators never need to type it. Removing the
          input on all four surfaces (add/edit single/batch) avoids forcing
          a choice that has no current runtime effect (the registry has no
          adapters registered yet, so all families resolve to estimated). */}

      {validationError && (
        <Alert type="error" showIcon title={t(validationError)} />
      )}
    </div>
  );

  // Both add and edit modes render as a flat panel. Required-field
  // asterisks (context_window, max_output_tokens) must be unmissable, and
  // hiding the controls behind a Collapse hides those asterisks.
  return <div className="space-y-2">{content}</div>;
};
