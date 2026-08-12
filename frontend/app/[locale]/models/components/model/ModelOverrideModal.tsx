"use client";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Modal, App, Tag } from "antd";

import type { ModelOption } from "@/types/modelConfig";
import { useInferenceFieldSpecs } from "@/hooks/model/useInferenceFieldSpecs";

import {
  ModelAdvancedSettings,
  ModelAdvancedSettingsValue,
  advancedSettingsValueFromRecord,
  buildModelOverrideEntry,
} from "./ModelAdvancedSettings";

// =============================================================================
// v2.6.0: ModelOverrideModal — reusable per-agent / per-KB model param override
// =============================================================================
// Renders ALL bound models in a vertical list. Each model has its own
// `ModelAdvancedSettings` section so the user can configure parameters for
// every model individually (not just one at a time).
//
// The override payload shape mirrors `ag_tenant_agent_t.model_params_override`:
//   { "<model_id>": { temperature?: number|null, top_p?: number|null, extra_params?: {...}|null } }
// =============================================================================

export interface ModelOverrideEntry {
  temperature?: number | null;
  top_p?: number | null;
  extra_params?: Record<string, unknown> | null;
  [key: string]: unknown;
}

export type ModelOverrideMap = Record<string, ModelOverrideEntry>;

export interface ModelOverrideModalProps {
  open: boolean;
  onClose: () => void;
  /** Bound models that the user can configure overrides for. */
  models: ModelOption[];
  /** Current override map. */
  value: ModelOverrideMap;
  /** Callback with the next full override map (not a delta). */
  onChange: (next: ModelOverrideMap) => void;
  /** Modal title override. */
  title?: string;
  /** Disable all inputs (e.g. read-only / generating). */
  disabled?: boolean;
}

export const ModelOverrideModal = ({
  open,
  onClose,
  models,
  value,
  onChange,
  title,
  disabled = false,
}: ModelOverrideModalProps) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { specs } = useInferenceFieldSpecs({ enabled: open });

  const handleFieldChange = (
    modelId: number,
    next: ModelAdvancedSettingsValue
  ) => {
    const entry = buildModelOverrideEntry(next);
    onChange({
      ...value,
      [String(modelId)]: entry,
    });
  };

  const handleClear = (modelId: number) => {
    const next = { ...value };
    delete next[String(modelId)];
    onChange(next);
    message.success(
      t("model.advanced.overrideCleared", {
        defaultValue: "已清空该模型的覆盖参数",
      })
    );
  };

  // Tag color per model type for visual distinction
  const typeColorMap: Record<string, string> = {
    llm: "blue",
    embedding: "green",
    multi_embedding: "lime",
    rerank: "orange",
    stt: "purple",
    tts: "magenta",
    vlm: "cyan",
    vlm2: "cyan",
    vlm3: "cyan",
  };

  const sections = useMemo(
    () =>
      models.map((model) => {
        const modelType = model.type ?? "llm";
        const entry = value[String(model.id)] ?? {};
        const hasOverride = Object.keys(entry).length > 0;
        // When no per-agent/per-KB override exists yet, fall back to the
        // model-level defaults (temperature/top_p/extra_params, including
        // __custom__) so the user can see the currently effective values.
        // Once an override exists, it takes precedence.
        const formRecord = hasOverride
          ? entry
          : {
              temperature: model.temperature,
              top_p: model.topP,
              extra_params: model.extraParams,
            };
        const formValue = advancedSettingsValueFromRecord(
          formRecord,
          specs,
          modelType
        );
        return { model, modelType, formValue, hasOverride };
      }),
    [models, value, specs]
  );

  return (
    <Modal
      title={
        title ||
        t("model.advanced.overrideTitle", {
          defaultValue: "模型参数覆盖",
        })
      }
      open={open}
      onCancel={onClose}
      onOk={onClose}
      okText={t("common.confirm", { defaultValue: "确定" })}
      cancelText={t("common.cancel", { defaultValue: "取消" })}
      okButtonProps={{ disabled }}
      cancelButtonProps={{ disabled }}
      width={760}
      centered
      destroyOnClose={false}
      styles={{ body: { maxHeight: "70vh", overflowY: "auto" } }}
    >
      {models.length === 0 ? (
        <div className="text-gray-500 text-sm py-8 text-center">
          {t("model.advanced.noModelsAvailable", {
            defaultValue: "当前未绑定可用模型",
          })}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="text-xs text-gray-500 pb-2 border-b border-gray-100">
            {t("model.advanced.overrideHint", {
              defaultValue: "留空表示继承模型默认值。",
            })}
          </div>
          {sections.map(({ model, modelType, formValue, hasOverride }) => (
            <div
              key={model.id}
              className="border border-gray-200 rounded-lg p-4 space-y-3"
            >
              {/* Model header */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm text-gray-800">
                    {model.displayName || model.name}
                  </span>
                  <Tag color={typeColorMap[modelType] || "default"}>
                    {modelType}
                  </Tag>
                  {hasOverride && (
                    <Tag color="volcano" className="ml-1">
                      {t("model.advanced.overrideBadge", {
                        defaultValue: "已覆盖",
                      })}
                    </Tag>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => handleClear(model.id)}
                  disabled={disabled || !hasOverride}
                  className="text-xs text-red-500 hover:text-red-600 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {t("model.advanced.clearOverride", {
                    defaultValue: "清空该模型的覆盖",
                  })}
                </button>
              </div>

              {/* Per-model advanced settings */}
              <ModelAdvancedSettings
                modelType={modelType}
                specs={specs}
                value={formValue}
                onChange={(next) => handleFieldChange(model.id, next)}
                mode="override"
                disabled={disabled}
              />
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
};

export default ModelOverrideModal;
