"use client";

import { useEffect } from "react";

import { Input, InputNumber, Select, Switch, Tooltip, Empty, Button } from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

import type {
  InferenceFieldSpec,
  InferenceFieldSpecsByType,
  InferenceFieldType,
} from "@/types/modelConfig";

// =============================================================================
// v2.6.0: ModelAdvancedSettings — per-type fixed-field form
// =============================================================================
// This component renders a dynamic form for the "advanced settings" of a model
// based on the spec returned by GET /model/catalog/inference_field_specs.
// Each model type (llm / embedding / rerank / stt / tts / vlm*) has its own
// fixed list of fields; the spec drives both rendering and validation.
//
// Two modes:
//  - "default": model-level defaults (ModelAddDialogV2 / ModelEditDialog).
//      Empty fields are saved as null/undefined, meaning "inherit provider default".
//  - "override": per-agent / per-KB override (Agent/KB advanced settings modal).
//      Empty fields are saved as null, meaning "inherit model default".
//
// Storage mapping (handled by caller via buildInferenceParamsPayload):
//  - display_name → model_record_t.display_name column.
//  - context_window_tokens / max_input_tokens / max_output_tokens /
//    default_output_reserve_tokens / tokenizer_family → existing W1 columns
//    (rendered by ModelCapacityFields in default mode).
//  - dimension / model_factory / model_appid / access_token / max_tokens →
//    existing columns.
//  - temperature / top_p / extra_params and other v2.6.0 additions are NOT
//    included — the new dialog matches the original ModelAddDialog's parameter
//    set without adding new inference parameters.
//  - __custom__ (user-defined key/value pairs) → extra_params.__custom__
//    sub-object on the wire (dict of string -> string). In the editing state
//    (ModelAdvancedSettingsValue), __custom__ is a [string, string][] entries
//    array so the user can edit empty/duplicate keys; buildInferenceParamsPayload
//    converts it to a clean dict on save. Backend filter_extra_params validates
//    the dict shape and passes through. No DB schema change required.
// =============================================================================

export interface ModelAdvancedSettingsValue {
  /** snake_case key → value, mirroring the spec's `key` field */
  [key: string]: unknown;
}

export type ModelAdvancedSettingsMode = "default" | "override";

export interface ModelAdvancedSettingsProps {
  /** Current model type, e.g. "llm" / "embedding" / "stt". */
  modelType: string;
  /** Full specs payload (all types). The component picks the current type's list. */
  specs: InferenceFieldSpecsByType;
  /** Current form values (snake_case keys matching spec). */
  value: ModelAdvancedSettingsValue;
  /** Callback with the next full value object (not a delta). */
  onChange: (next: ModelAdvancedSettingsValue) => void;
  /** "default" = model-level (empty = inherit provider); "override" = per-agent/KB (empty = inherit model). Default "default". */
  mode?: ModelAdvancedSettingsMode;
  /** Disable all inputs. */
  disabled?: boolean;
}

/** Keys that have dedicated DB columns or are stored as top-level fields (not in extra_params). */
const DEDICATED_KEYS = new Set<string>([
  "display_name",
  "temperature",
  "top_p",
  "context_window_tokens",
  "max_input_tokens",
  "max_output_tokens",
  "default_output_reserve_tokens",
  "tokenizer_family",
  "dimension",
  "expected_chunk_size",
  "maximum_chunk_size",
  "chunk_batch",
  "model_factory",
  "model_appid",
  "access_token",
  "max_tokens",
  "timeout_seconds",
  "concurrency_limit",
]);

/**
 * Capacity field keys that are rendered by the dedicated `ModelCapacityFields`
 * component (可选容量配置). They are excluded from the advanced-settings form to
 * avoid showing the same fields twice when both panels are displayed together
 * (e.g. in the add/edit model gear modal). These fields still flow through
 * `buildInferenceParamsPayload` if present in the form state, so existing
 * values are never lost — they are simply edited in the capacity panel.
 */
const CAPACITY_FIELD_KEYS = new Set<string>([
  "context_window_tokens",
  "max_input_tokens",
  "max_output_tokens",
  "default_output_reserve_tokens",
  "tokenizer_family",
]);

/**
 * Embedding-specific field keys that are rendered by dedicated UI components
 * (ModelChunkSizeSlider for chunk size range, separate Input for dimension and
 * chunk_batch) in the add/edit model dialog, mirroring the original
 * ModelAddDialog. They are excluded from the advanced-settings form in default
 * mode to avoid duplication. In override mode (per-agent/per-KB), they are
 * still shown since there is no separate dedicated panel.
 */
const EMBEDDING_FIELD_KEYS = new Set<string>([
  "dimension",
  "expected_chunk_size",
  "maximum_chunk_size",
  "chunk_batch",
]);

/**
 * Removed advanced parameter keys. These were newly added in v2.6.0 but were
 * not present in the original ModelAddDialog. They are excluded from rendering,
 * initialization, and submission to ensure the new dialog does not add more
 * parameters than the original.
 *
 * Note: temperature and top_p are intentionally NOT in this set for LLM —
 * they are now exposed via FIXED_INFERENCE_FIELDS_BY_TYPE["llm"] and stored
 * in dedicated DB columns. enable_thinking is stored in extra_params JSONB.
 */
const REMOVED_ADVANCED_PARAM_KEYS = new Set<string>([
  "frequency_penalty",
  "presence_penalty",
  "stop",
  "seed",
  "encoding_format",
  "top_n",
  "language",
  "response_format",
  "voice",
  "speed",
]);

/**
 * Split a form-state object into the wire payload shape consumed by the
 * backend create/update endpoints:
 *   - temperature / top_p at the top level
 *   - capacity fields at the top level (existing W1 columns)
 *   - everything else goes into `extra_params`
 *
 * Empty / undefined values are dropped so the backend treats them as "inherit".
 */
export const buildInferenceParamsPayload = (
  value: ModelAdvancedSettingsValue
): {
  temperature?: number;
  top_p?: number;
  extra_params?: Record<string, unknown>;
  [key: string]: unknown;
} => {
  const result: Record<string, unknown> = {};
  const extraParams: Record<string, unknown> = {};

  for (const [key, raw] of Object.entries(value)) {
    if (raw === undefined || raw === null || raw === "") continue;
    if (REMOVED_ADVANCED_PARAM_KEYS.has(key)) continue;
    if (key === "__custom__") {
      // value.__custom__ is the editing-state entries array ([string, string][]),
      // which may contain empty/duplicate keys. Convert to a clean dict for the
      // wire payload: empty keys dropped, duplicates collapse (last-wins).
      const entries = Array.isArray(raw) ? (raw as [string, string][]) : [];
      const dict: Record<string, string> = {};
      for (const [k, v] of entries) {
        if (k === "") continue;
        dict[k] = v;
      }
      if (Object.keys(dict).length > 0) {
        extraParams["__custom__"] = dict;
      }
      continue;
    }
    if (DEDICATED_KEYS.has(key)) {
      result[key] = raw;
    } else {
      extraParams[key] = raw;
    }
  }

  if (Object.keys(extraParams).length > 0) {
    result.extra_params = extraParams;
  }
  return result;
};

/**
 * Build the per-model override entry stored inside
 * `ag_tenant_agent_t.model_params_override` JSONB.
 * Includes all configured fields except `display_name` (model name is not
 * overridable per-agent/per-KB).
 */
export const buildModelOverrideEntry = (
  value: ModelAdvancedSettingsValue
): {
  temperature?: number | null;
  top_p?: number | null;
  extra_params?: Record<string, unknown> | null;
  [key: string]: unknown;
} => {
  const payload = buildInferenceParamsPayload(value);
  const entry: Record<string, unknown> = {};
  for (const [key, val] of Object.entries(payload)) {
    // display_name is a model-level property, not overridable per-agent/per-KB.
    if (key === "display_name") continue;
    entry[key] = val;
  }
  return entry;
};

/** Convert a spec value (could be number / string / boolean / string[]) into a form-state value. */
const normalizeInitialValue = (raw: unknown): unknown => {
  if (Array.isArray(raw)) return raw;
  return raw;
};

/**
 * Initialize a form-state object from an existing model / override record.
 * Pass in the model record (for "default" mode) or the per-model override
 * entry (for "override" mode) — the function flattens top-level + extra_params
 * back into a single snake_case-keyed object keyed by spec.key.
 */
export const advancedSettingsValueFromRecord = (
  record: {
    temperature?: number | null;
    top_p?: number | null;
    extra_params?: Record<string, unknown> | null;
    [key: string]: unknown;
  } | null | undefined,
  specs: InferenceFieldSpecsByType,
  modelType: string
): ModelAdvancedSettingsValue => {
  const value: ModelAdvancedSettingsValue = {};
  if (!record) return value;

  const specList = specs[modelType] || [];
  const extra = record.extra_params || {};

  for (const spec of specList) {
    if (REMOVED_ADVANCED_PARAM_KEYS.has(spec.key)) continue;
    if (spec.key in record) {
      value[spec.key] = normalizeInitialValue(record[spec.key]);
    } else if (spec.key in extra) {
      value[spec.key] = normalizeInitialValue(extra[spec.key]);
    }
  }

  // Pass through user-defined custom params (extra_params.__custom__).
  // Backend stores a dict; the editor works on a [string, string][] entries
  // array so the user can edit empty/duplicate keys before commit.
  const customRaw = "__custom__" in record ? record["__custom__"] : extra["__custom__"];
  if (customRaw && typeof customRaw === "object" && !Array.isArray(customRaw)) {
    value["__custom__"] = Object.entries(customRaw as Record<string, string>);
  }
  return value;
};

// =============================================================================
// Field renderers
// =============================================================================

const renderStringField = (
  spec: InferenceFieldSpec,
  value: unknown,
  onChange: (next: unknown) => void,
  disabled: boolean,
  placeholder?: string
) => (
  <Input
    className="w-full"
    value={(value as string) ?? ""}
    placeholder={placeholder}
    disabled={disabled}
    onChange={(e) => onChange(e.target.value)}
  />
);

const renderIntField = (
  spec: InferenceFieldSpec,
  value: unknown,
  onChange: (next: unknown) => void,
  disabled: boolean
) => (
  <InputNumber
    className="w-full"
    style={{ width: "100%" }}
    value={value === null || value === undefined ? null : Number(value)}
    disabled={disabled}
    step={1}
    precision={0}
    min={spec.range ? spec.range[0] : undefined}
    max={spec.range ? spec.range[1] : undefined}
    onChange={(next) => onChange(next === null ? undefined : next)}
  />
);

const renderFloatField = (
  spec: InferenceFieldSpec,
  value: unknown,
  onChange: (next: unknown) => void,
  disabled: boolean
) => (
  <InputNumber
    className="w-full"
    style={{ width: "100%" }}
    value={value === null || value === undefined ? null : Number(value)}
    disabled={disabled}
    step={0.1}
    min={spec.range ? spec.range[0] : undefined}
    max={spec.range ? spec.range[1] : undefined}
    onChange={(next) => onChange(next === null ? undefined : next)}
  />
);

const renderBoolField = (
  spec: InferenceFieldSpec,
  value: unknown,
  onChange: (next: unknown) => void,
  disabled: boolean
) => (
  <Switch
    checked={Boolean(value)}
    disabled={disabled}
    onChange={(checked) => onChange(checked)}
  />
);

/** Chinese display labels for STT/TTS provider option values. The option
 * value (e.g. "dashscope") is preserved as-is for backend logic and the
 * volcengine conditional render; only the shown label is localized, mirroring
 * the original ModelAddDialog ("阿里灵积" / "火山引擎"). */
const PROVIDER_OPTION_LABELS: Record<string, string> = {
  dashscope: "阿里灵积",
  volcengine: "火山引擎",
};

const renderSelectField = (
  spec: InferenceFieldSpec,
  value: unknown,
  onChange: (next: unknown) => void,
  disabled: boolean
) => (
  <Select
    className="w-full"
    value={(value as string) ?? undefined}
    disabled={disabled}
    allowClear
    options={(spec.options || []).map((opt) => ({
      value: opt,
      label: PROVIDER_OPTION_LABELS[opt] ?? opt,
    }))}
    onChange={(next) => onChange(next ?? undefined)}
  />
);

const renderArrayStrField = (
  spec: InferenceFieldSpec,
  value: unknown,
  onChange: (next: unknown) => void,
  disabled: boolean
) => (
  <Select
    mode="tags"
    className="w-full"
    style={{ width: "100%" }}
    value={Array.isArray(value) ? (value as string[]) : []}
    disabled={disabled}
    tokenSeparators={[",", " "]}
    maxCount={spec.max_items ?? undefined}
    notFoundContent={null}
    placeholder=""
    onChange={(next) => onChange(next)}
  />
);

const renderFieldControl = (
  spec: InferenceFieldSpec,
  value: unknown,
  onChange: (next: unknown) => void,
  disabled: boolean
) => {
  const type: InferenceFieldType = spec.type;
  switch (type) {
    case "str":
      return renderStringField(spec, value, onChange, disabled);
    case "int":
      return renderIntField(spec, value, onChange, disabled);
    case "float":
      return renderFloatField(spec, value, onChange, disabled);
    case "bool":
      return renderBoolField(spec, value, onChange, disabled);
    case "select":
      return renderSelectField(spec, value, onChange, disabled);
    case "array_str":
      return renderArrayStrField(spec, value, onChange, disabled);
    default:
      return renderStringField(spec, value, onChange, disabled);
  }
};

// =============================================================================
// Custom key/value params section
// =============================================================================
// Renders a list of (key, value) input pairs the user can freely add/remove.
// Validation is intentionally minimal: duplicate keys show a red hint but do
// NOT block save — the user is responsible for parameter correctness.
// On commit, empty keys are dropped and duplicate keys collapse (last-wins).

type TFunc = ReturnType<typeof useTranslation>["t"];

interface CustomParamsSectionProps {
  t: TFunc;
  customEntries: [string, string][];
  hasDuplicateKey: boolean;
  disabled: boolean;
  onAdd: () => void;
  onRemove: (idx: number) => void;
  onKeyChange: (idx: number, nextKey: string) => void;
  onValueChange: (idx: number, nextValue: string) => void;
}

const renderCustomParamsSection = ({
  t,
  customEntries,
  hasDuplicateKey,
  disabled,
  onAdd,
  onRemove,
  onKeyChange,
  onValueChange,
}: CustomParamsSectionProps) => {
  return (
    <div className="border-t border-gray-200 pt-3 mt-3">
      <div className="flex items-center justify-between mb-2">
        <label className="block text-sm font-medium text-gray-700">
          <Tooltip
            title={t("model.advanced.customParamsHint", {
              defaultValue:
                "自定义参数将原样传给模型提供方，请自行确认参数名与取值是否正确。",
            })}
          >
            <span>
              {t("model.advanced.customParams", {
                defaultValue: "自定义参数",
              })}
            </span>
          </Tooltip>
        </label>
        <Button
          size="small"
          type="dashed"
          icon={<PlusOutlined />}
          onClick={onAdd}
          disabled={disabled}
        >
          {t("model.advanced.addCustomParam", {
            defaultValue: "添加参数",
          })}
        </Button>
      </div>

      {customEntries.length === 0 ? (
        <div className="text-xs text-gray-400">
          {t("model.advanced.noCustomParams", {
            defaultValue: "暂无自定义参数",
          })}
        </div>
      ) : (
        <div className="space-y-2">
          {customEntries.map(([k, v], idx) => {
            const isDuplicate =
              k !== "" &&
              customEntries.filter(([ek]) => ek === k).length > 1;
            return (
              <div key={idx} className="flex items-center gap-2">
                <Input
                  className="flex-1"
                  size="small"
                  placeholder={t("model.advanced.customKeyPlaceholder", {
                    defaultValue: "参数名",
                  })}
                  value={k}
                  disabled={disabled}
                  status={isDuplicate ? "error" : undefined}
                  onChange={(e) => onKeyChange(idx, e.target.value)}
                />
                <Input
                  className="flex-1"
                  size="small"
                  placeholder={t("model.advanced.customValuePlaceholder", {
                    defaultValue: "参数值",
                  })}
                  value={v}
                  disabled={disabled}
                  onChange={(e) => onValueChange(idx, e.target.value)}
                />
                <Button
                  size="small"
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => onRemove(idx)}
                  disabled={disabled}
                />
              </div>
            );
          })}
          {hasDuplicateKey && (
            <div className="text-xs text-red-500">
              {t("model.advanced.duplicateKeyWarning", {
                defaultValue:
                  "存在重复的参数名，请检查（重复参数保存时仅保留最后一个）。",
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// =============================================================================
// Main component
// =============================================================================

export const ModelAdvancedSettings = ({
  modelType,
  specs,
  value,
  onChange,
  mode = "default",
  disabled = false,
}: ModelAdvancedSettingsProps) => {
  const { t } = useTranslation();
  // STT/TTS auth fields (AppID, Access Token) only apply to Volcano Engine.
  // DashScope uses the top-level API Key instead. Mirrors the original
  // ModelAddDialog, which conditionally rendered these fields only when the
  // provider was "volcengine". Applied in default mode (add/edit model); in
  // override mode all non-removed fields remain visible.
  const isVoiceType = modelType === "stt" || modelType === "tts";
  const isVolcengineVoice =
    isVoiceType && mode === "default" && (value.model_factory as string) === "volcengine";

  // STT/TTS default provider to DashScope (阿里灵积) when empty, matching the
  // original ModelAddDialog (sttProvider/ttsProvider: "dashscope"). Applied
  // inside the component so the default takes effect regardless of how the
  // parent initialized state (custom flow type-switch, batch row creation, or
  // dialog reopen). Only in default mode: override mode leaves empty as
  // "inherit model default".
  useEffect(() => {
    if (
      isVoiceType &&
      mode === "default" &&
      !value.model_factory
    ) {
      onChange({ ...value, model_factory: "dashscope" });
    }
  }, [isVoiceType, mode, value, onChange]);

  // Filter out:
  //  - capacity fields in default mode: rendered by the dedicated
  //    `ModelCapacityFields` panel, so showing them here would duplicate the
  //    controls. In override mode (per-agent/per-KB) there is no separate
  //    capacity panel, so capacity fields ARE shown here.
  //  - display_name in override mode: it's a model-level property, not an
  //    inference parameter that can be overridden per-agent/per-KB.
  const specList: InferenceFieldSpec[] = (specs[modelType] || []).filter((spec) => {
    if (REMOVED_ADVANCED_PARAM_KEYS.has(spec.key)) return false;
    if (mode === "default" && CAPACITY_FIELD_KEYS.has(spec.key)) return false;
    if (mode === "default" && EMBEDDING_FIELD_KEYS.has(spec.key)) return false;
    if (mode === "override" && spec.key === "display_name") return false;
    if (
      isVoiceType &&
      mode === "default" &&
      (spec.key === "model_appid" || spec.key === "access_token") &&
      !isVolcengineVoice
    ) {
      return false;
    }
    return true;
  });

  const handleFieldChange = (key: string, next: unknown) => {
    onChange({ ...value, [key]: next });
  };

  // ---------- Custom key/value params ----------
  // value.__custom__ holds the editing-state entries array ([string, string][]),
  // which may contain empty/duplicate keys during editing. The wire payload
  // conversion (buildInferenceParamsPayload) cleans it up on save.
  const CUSTOM_KEY = "__custom__";
  const customEntries: [string, string][] = (() => {
    const raw = value[CUSTOM_KEY];
    return Array.isArray(raw) ? (raw as [string, string][]) : [];
  })();
  const hasDuplicateKey = customEntries.some(
    ([k], i) => k !== "" && customEntries.findIndex(([k2]) => k2 === k) !== i
  );

  const commitCustomEntries = (nextEntries: [string, string][]) => {
    onChange({ ...value, [CUSTOM_KEY]: nextEntries });
  };

  const handleAddCustomParam = () => {
    commitCustomEntries([...customEntries, ["", ""]]);
  };

  const handleRemoveCustomParam = (idx: number) => {
    commitCustomEntries(customEntries.filter((_, i) => i !== idx));
  };

  const handleCustomKeyChange = (idx: number, nextKey: string) => {
    const next = customEntries.map(([k, v], i) =>
      i === idx ? [nextKey, v] : [k, v]
    ) as [string, string][];
    commitCustomEntries(next);
  };

  const handleCustomValueChange = (idx: number, nextValue: string) => {
    const next = customEntries.map(([k, v], i) =>
      i === idx ? [k, nextValue] : [k, v]
    ) as [string, string][];
    commitCustomEntries(next);
  };

  if (specList.length === 0) {
    return (
      <div className="space-y-3">
        <Empty
          description={t("model.advanced.noFieldsForType", {
            defaultValue: "No advanced settings for this model type.",
          })}
        />
        {renderCustomParamsSection({
          t,
          customEntries,
          hasDuplicateKey,
          disabled,
          onAdd: handleAddCustomParam,
          onRemove: handleRemoveCustomParam,
          onKeyChange: handleCustomKeyChange,
          onValueChange: handleCustomValueChange,
        })}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {mode === "override" && (
        <div className="text-xs text-gray-500">
          {t("model.advanced.overrideHint", {
            defaultValue:
              "Leave a field empty to inherit the model's default value.",
          })}
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {specList.map((spec) => {
          const fieldValue = value[spec.key];
          const rangeHint =
            spec.range && spec.range.length === 2
              ? `(${spec.range[0]} – ${spec.range[1]})`
              : null;
          return (
            <div key={spec.key}>
              <label className="block mb-1 text-sm font-medium text-gray-700">
                <Tooltip
                  title={
                    rangeHint
                      ? `${spec.label} ${rangeHint}`
                      : spec.label
                  }
                >
                  <span>{spec.label}</span>
                </Tooltip>
                {rangeHint && (
                  <span className="ml-1 text-xs text-gray-400">
                    {rangeHint}
                  </span>
                )}
              </label>
              {renderFieldControl(
                spec,
                fieldValue,
                (next) => handleFieldChange(spec.key, next),
                disabled
              )}
            </div>
          );
        })}
      </div>
      {renderCustomParamsSection({
        t,
        customEntries,
        hasDuplicateKey,
        disabled,
        onAdd: handleAddCustomParam,
        onRemove: handleRemoveCustomParam,
        onKeyChange: handleCustomKeyChange,
        onValueChange: handleCustomValueChange,
      })}
    </div>
  );
};

export default ModelAdvancedSettings;
