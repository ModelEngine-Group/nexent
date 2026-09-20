"use client";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Select, Tag, Tooltip } from "antd";
import { Info } from "lucide-react";

import { ModelOption, ModelType } from "@/types/modelConfig";

/**
 * v2.6.1 redesign: one default-model slot in the flat "默认配置" grid.
 *
 * Replaces the DefaultModelDialog approach (open a modal to configure slots)
 * with inline selects, following the v0 design: every slot is visible at a
 * glance, carries a priority badge, an explanatory tooltip, the selected
 * model's connectivity dot, and a provider badge.
 */

export type ModelSlotPriority = "required" | "recommended" | "optional";

export interface ModelSlotDef {
  /** category key in the selectedModels structure, e.g. "llm". */
  category: string;
  /** option key in the selectedModels structure, e.g. "main". */
  option: string;
  /** wire key for the highlight-missing-field event, e.g. "llm.main". */
  fieldKey: string;
  /** the model type this slot accepts. */
  modelType: ModelType;
  /** slot display label. */
  label: string;
  /** configuration priority shown next to the label. */
  priority: ModelSlotPriority;
  /** tooltip explaining when this slot is needed. */
  hint: string;
}

const STATUS_DOT_CLASS: Record<string, string> = {
  available: "bg-emerald-500",
  unavailable: "bg-red-500",
  detecting: "bg-amber-400 animate-pulse",
  not_detected: "bg-slate-300",
};

function StatusDot({ status }: { status?: string }) {
  const cls = (status && STATUS_DOT_CLASS[status]) || "bg-slate-300";
  return (
    <span className={`inline-block size-2 shrink-0 rounded-full ${cls}`} />
  );
}

/**
 * All default-model slots, flattened. Mirrors the previous DefaultModelDialog
 * grouping (llm / embedding / reranker / multimodal / voice) but rendered as
 * one grid. Priorities follow the v0 design: LLM is required, embedding and
 * image understanding are recommended, everything else is optional.
 */
export function buildModelSlots(
  t: (key: string, opts?: any) => string
): ModelSlotDef[] {
  return [
    {
      category: "llm",
      option: "main",
      fieldKey: "llm.main",
      modelType: "llm" as ModelType,
      label: t("model.type.llm", { defaultValue: "大语言模型" }),
      priority: "required",
      hint: t("modelConfig.slot.hint.llm", {
        defaultValue:
          "平台对话、推理与知识问答的核心能力，必须配置后系统才能正常运行。",
      }),
    },
    {
      category: "embedding",
      option: "embedding",
      fieldKey: "embedding.embedding",
      modelType: "embedding" as ModelType,
      label: t("model.type.embedding", { defaultValue: "文本嵌入" }),
      priority: "recommended",
      hint: t("modelConfig.slot.hint.embedding", {
        defaultValue:
          "用于知识库文档向量化与语义检索，构建知识库或开启记忆时需要配置。",
      }),
    },
    {
      category: "multimodal",
      option: "vlm",
      fieldKey: "multimodal.vlm",
      modelType: "vlm" as ModelType,
      label: t("model.type.imageUnderstanding", { defaultValue: "图像理解" }),
      priority: "recommended",
      hint: t("modelConfig.slot.hint.vlm", {
        defaultValue:
          "用于理解图片内容并进行图文问答，需要图片理解能力时推荐配置。",
      }),
    },
    {
      category: "embedding",
      option: "multi_embedding",
      fieldKey: "embedding.multi_embedding",
      modelType: "multi_embedding" as ModelType,
      label: t("model.type.multiEmbedding", { defaultValue: "多模态嵌入" }),
      priority: "optional",
      hint: t("modelConfig.slot.hint.multiEmbedding", {
        defaultValue: "用于图文混合内容的向量化检索，有多模态检索需求时配置。",
      }),
    },
    {
      category: "reranker",
      option: "reranker",
      fieldKey: "reranker.reranker",
      modelType: "rerank" as ModelType,
      label: t("model.type.rerank", { defaultValue: "重排" }),
      priority: "optional",
      hint: t("modelConfig.slot.hint.rerank", {
        defaultValue:
          "对检索结果进行精排以提升相关性，追求更高检索质量时配置。",
      }),
    },
    {
      category: "multimodal",
      option: "vlm2",
      fieldKey: "multimodal.vlm2",
      modelType: "vlm2" as ModelType,
      label: t("model.type.imageGeneration", { defaultValue: "图像生成" }),
      priority: "optional",
      hint: t("modelConfig.slot.hint.vlm2", {
        defaultValue: "用于根据文本描述生成图片，需要文生图能力时配置。",
      }),
    },
    {
      category: "multimodal",
      option: "vlm3",
      fieldKey: "multimodal.vlm3",
      modelType: "vlm3" as ModelType,
      label: t("model.type.videoUnderstanding", { defaultValue: "视频理解" }),
      priority: "optional",
      hint: t("modelConfig.slot.hint.vlm3", {
        defaultValue: "用于理解视频内容并进行问答，需要视频理解能力时配置。",
      }),
    },
    {
      category: "multimodal",
      option: "vlm4",
      fieldKey: "multimodal.vlm4",
      modelType: "vlm4" as ModelType,
      label: t("model.type.audioUnderstanding", { defaultValue: "音频理解" }),
      priority: "optional",
      hint: t("modelConfig.slot.hint.vlm4", {
        defaultValue: "用于理解音频内容，需要音频理解能力时配置。",
      }),
    },
    {
      category: "voice",
      option: "stt",
      fieldKey: "voice.stt",
      modelType: "stt" as ModelType,
      label: t("model.type.stt", { defaultValue: "语音识别" }),
      priority: "optional",
      hint: t("modelConfig.slot.hint.stt", {
        defaultValue: "将语音转换为文本输入，需要语音输入能力时配置。",
      }),
    },
    {
      category: "voice",
      option: "tts",
      fieldKey: "voice.tts",
      modelType: "tts" as ModelType,
      label: t("model.type.tts", { defaultValue: "语音合成" }),
      priority: "optional",
      hint: t("modelConfig.slot.hint.tts", {
        defaultValue: "将文本转换为语音输出，需要语音播报能力时配置。",
      }),
    },
  ];
}

const PRIORITY_LABELS: Record<ModelSlotPriority, string> = {
  required: "（必填）",
  recommended: "（推荐）",
  optional: "（可选）",
};

export function ModelSlotSelect({
  slot,
  models,
  value,
  error,
  disabled,
  onChange,
}: {
  slot: ModelSlotDef;
  models: ModelOption[];
  /** displayName of the selected model; "" means "not used". */
  value: string;
  /** highlight the slot (missing required field event). */
  error?: boolean;
  disabled?: boolean;
  onChange: (displayName: string) => void;
}) {
  const { t } = useTranslation();

  const options = useMemo(
    () => models.filter((m) => m.type === slot.modelType),
    [models, slot.modelType]
  );
  const selected = options.find((m) => m.displayName === value) ?? null;

  return (
    <div
      className="space-y-1.5"
      data-error-field={error ? slot.fieldKey : undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-1">
          <label className="truncate text-sm font-medium text-foreground">
            {slot.label}
          </label>
          {slot.priority !== "optional" && (
            <span className="shrink-0 text-xs font-normal leading-none text-muted-foreground">
              {PRIORITY_LABELS[slot.priority]}
            </span>
          )}
          <Tooltip title={slot.hint}>
            <button
              type="button"
              aria-label={`${slot.label}说明`}
              className="text-muted-foreground/60 transition-colors hover:text-foreground"
            >
              <Info className="size-3.5" />
            </button>
          </Tooltip>
        </span>
        {selected && (
          <Tag className="m-0 shrink-0 text-[10px]">{selected.source}</Tag>
        )}
      </div>

      <Select
        className="w-full"
        size="middle"
        status={error ? "error" : undefined}
        disabled={disabled}
        value={value || "__none__"}
        onChange={(v) => onChange(v === "__none__" ? "" : v)}
        popupMatchSelectWidth={false}
      >
        <Select.Option value="__none__" className="text-muted-foreground">
          <span className="text-muted-foreground">
            {t("modelConfig.slot.notUsed", { defaultValue: "不使用" })}
          </span>
        </Select.Option>
        {options.length === 0 ? (
          <Select.Option value="__empty__" disabled>
            <span className="text-muted-foreground">
              {t("modelConfig.slot.noModels", {
                defaultValue: "暂无该类型模型，请先添加",
              })}
            </span>
          </Select.Option>
        ) : (
          options.map((m) => (
            <Select.Option
              key={`${m.id}-${m.displayName}`}
              value={m.displayName}
            >
              <span className="flex items-center gap-2">
                <StatusDot status={m.connect_status} />
                <span className="max-w-52 truncate">{m.displayName}</span>
              </span>
            </Select.Option>
          ))
        )}
      </Select>

      {/* status hint below the select */}
      {selected && (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <StatusDot status={selected.connect_status} />
          {t(`model.connectivity.${selected.connect_status}`, {
            defaultValue: selected.connect_status ?? "",
          })}
        </p>
      )}
    </div>
  );
}
