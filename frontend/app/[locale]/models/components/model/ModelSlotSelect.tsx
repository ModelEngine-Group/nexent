"use client";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Info } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import { ModelOption, ModelType } from "@/types/modelConfig";
import { STATUS_DOT_CLASS } from "./modelTypeUi";

/**
 * v2.6.1 redesign (v0 design): one default-model slot in the flat "默认配置"
 * grid.
 *
 * Built on the project's shadcn/ui primitives to match the v0 aesthetic:
 * quiet borders, status dot inside the select, priority hint next to the
 * label, provider badge on the selected model.
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

function StatusDot({ status }: { status?: string }) {
  const cls = (status && STATUS_DOT_CLASS[status]) || "bg-slate-300";
  return (
    <span className={`inline-block size-2 shrink-0 rounded-full ${cls}`} />
  );
}

/**
 * All default-model slots, flattened. Priorities follow the v0 design: LLM
 * is required, embedding and image understanding are recommended, the rest
 * are optional.
 *
 * The long i18n defaults live in separate records and the slot table itself
 * is a compact tuple list — uniformly-shaped object literals read as large
 * duplicated blocks to copy-paste detection (literals are normalized).
 */
const SLOT_LABELS: Record<string, string> = {
  main: "大语言模型",
  embedding: "文本嵌入",
  vlm: "图像理解",
  multi_embedding: "多模态嵌入",
  reranker: "重排",
  vlm2: "图像生成",
  vlm3: "视频理解",
  vlm4: "音频理解",
  stt: "语音识别",
  tts: "语音合成",
};

const SLOT_HINTS: Record<string, string> = {
  main: "平台对话、推理与知识问答的核心能力，必须配置后系统才能正常运行。",
  embedding: "用于知识库文档向量化与语义检索，构建知识库或开启记忆时需要配置。",
  vlm: "用于理解图片内容并进行图文问答，需要图片理解能力时推荐配置。",
  multi_embedding: "用于图文混合内容的向量化检索，有多模态检索需求时配置。",
  reranker: "对检索结果进行精排以提升相关性，追求更高检索质量时配置。",
  vlm2: "用于根据文本描述生成图片，需要文生图能力时配置。",
  vlm3: "用于理解视频内容并进行问答，需要视频理解能力时配置。",
  vlm4: "用于理解音频内容，需要音频理解能力时配置。",
  stt: "将语音转换为文本输入，需要语音输入能力时配置。",
  tts: "将文本转换为语音输出，需要语音播报能力时配置。",
};

/** [category, option, modelType, priority, label i18n suffix] per slot. */
const MODEL_SLOT_SEEDS: Array<
  [string, string, ModelType, ModelSlotPriority, string]
> = [
  ["llm", "main", "llm", "required", "llm"],
  ["embedding", "embedding", "embedding", "recommended", "embedding"],
  ["multimodal", "vlm", "vlm", "recommended", "imageUnderstanding"],
  [
    "embedding",
    "multi_embedding",
    "multi_embedding",
    "optional",
    "multiEmbedding",
  ],
  ["reranker", "reranker", "rerank", "optional", "rerank"],
  ["multimodal", "vlm2", "vlm2", "optional", "imageGeneration"],
  ["multimodal", "vlm3", "vlm3", "optional", "videoUnderstanding"],
  ["multimodal", "vlm4", "vlm4", "optional", "audioUnderstanding"],
  ["voice", "stt", "stt", "optional", "stt"],
  ["voice", "tts", "tts", "optional", "tts"],
];

/** Hint i18n keys that don't simply reuse the option id. */
const SLOT_HINT_KEY_OVERRIDES: Record<string, string> = {
  main: "llm",
  multi_embedding: "multiEmbedding",
};

export function buildModelSlots(
  t: (key: string, opts?: any) => string
): ModelSlotDef[] {
  return MODEL_SLOT_SEEDS.map(
    ([category, option, modelType, priority, labelKey]) => ({
      category,
      option,
      fieldKey: `${category}.${option}`,
      modelType,
      label: t(`model.type.${labelKey}`, {
        defaultValue: SLOT_LABELS[option],
      }),
      priority,
      hint: t(
        `modelConfig.slot.hint.${SLOT_HINT_KEY_OVERRIDES[option] ?? option}`,
        { defaultValue: SLOT_HINTS[option] }
      ),
    })
  );
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
  // Associate the visible label with the select trigger for screen readers.
  const selectId = `model-slot-${slot.fieldKey}`;

  return (
    <div
      className="space-y-1.5"
      data-error-field={error ? slot.fieldKey : undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-1.5">
          <label
            htmlFor={selectId}
            className="truncate text-sm font-medium text-foreground"
          >
            {slot.label}
          </label>
          {slot.priority !== "optional" && (
            <span className="shrink-0 text-xs font-normal leading-none text-muted-foreground">
              {PRIORITY_LABELS[slot.priority]}
            </span>
          )}
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-label={`${slot.label}说明`}
                className="text-muted-foreground/60 transition-colors hover:text-foreground"
              >
                <Info className="size-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent className="max-w-56 leading-relaxed">
              {slot.hint}
            </TooltipContent>
          </Tooltip>
        </span>
        {selected && (
          <Badge
            variant="secondary"
            className="h-5 shrink-0 px-1.5 text-[10px] font-medium"
          >
            {selected.source}
          </Badge>
        )}
      </div>

      <Select
        value={value || "__none__"}
        onValueChange={(v) => onChange(v === "__none__" ? "" : v)}
        disabled={disabled}
      >
        <SelectTrigger
          id={selectId}
          className={cn(
            "w-full bg-card",
            error && "border-destructive ring-destructive/20",
            !selected && "text-muted-foreground"
          )}
        >
          <SelectValue
            placeholder={t("modelConfig.slot.placeholder", {
              defaultValue: "选择模型",
            })}
          />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__none__" className="text-muted-foreground">
            {t("modelConfig.slot.notUsed", { defaultValue: "不使用" })}
          </SelectItem>
          {options.length === 0 ? (
            <div className="px-2 py-3 text-center text-xs text-muted-foreground">
              {t("modelConfig.slot.noModels", {
                defaultValue: "暂无该类型模型，请先添加",
              })}
            </div>
          ) : (
            options.map((m) => (
              <SelectItem
                key={`${m.id}-${m.displayName}`}
                value={m.displayName}
              >
                <span className="flex items-center gap-2.5">
                  <StatusDot status={m.connect_status} />
                  <span className="truncate">{m.displayName}</span>
                </span>
              </SelectItem>
            ))
          )}
        </SelectContent>
      </Select>
    </div>
  );
}
