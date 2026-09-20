"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input, Select, Tag, Tooltip } from "antd";
import {
  Pencil,
  Trash2,
  ShieldCheck,
  Search,
  PackageOpen,
  ChevronLeft,
  ChevronRight,
  Loader2,
} from "lucide-react";

import { MODEL_TYPES, MODEL_SOURCES } from "@/const/modelConfig";
import {
  ModelOption,
  ModelType,
  ModelSource,
  ModelConnectStatus,
} from "@/types/modelConfig";

/**
 * v2.6.1 redesign (v0 design): the model library as a custom list.
 *
 * Replaces the previous antd Table with the v0 layout: toolbar (search +
 * type + provider filters), lightweight rows (name + default badge, type
 * badge, provider, connectivity dot, icon actions) and custom pagination.
 */

const PAGE_SIZE = 8;

const STATUS_DOT_CLASS: Record<string, string> = {
  available: "bg-emerald-500",
  unavailable: "bg-red-500",
  detecting: "bg-amber-400 animate-pulse",
  not_detected: "bg-slate-300",
};

const STATUS_LABEL_KEYS: Record<string, string> = {
  available: "model.status.available",
  unavailable: "model.status.unavailable",
  detecting: "model.status.detecting",
  not_detected: "model.status.notDetected",
};

const STATUS_FALLBACK_LABELS: Record<string, string> = {
  available: "可用",
  unavailable: "不可用",
  detecting: "检测中",
  not_detected: "未检测",
};

// Raw type ids -> the semantic i18n keys used across the app. Mirrors the
// mapping the previous table column used (vlm2/vlm3/vlm4 have no direct
// model.type.<id> keys).
const TYPE_LABEL_KEY_MAP: Record<string, string> = {
  llm: "llm",
  embedding: "embedding",
  multi_embedding: "multiEmbedding",
  vlm: "imageUnderstanding",
  vlm2: "imageGeneration",
  vlm3: "videoUnderstanding",
  vlm4: "audioUnderstanding",
  rerank: "rerank",
  stt: "stt",
  tts: "tts",
};

const TYPE_BADGE_COLORS: Record<string, string> = {
  [MODEL_TYPES.LLM]: "blue",
  [MODEL_TYPES.EMBEDDING]: "geekblue",
  [MODEL_TYPES.MULTI_EMBEDDING]: "cyan",
  [MODEL_TYPES.RERANK]: "purple",
  [MODEL_TYPES.STT]: "orange",
  [MODEL_TYPES.TTS]: "magenta",
  [MODEL_TYPES.VLM]: "green",
  [MODEL_TYPES.VLM2]: "green",
  [MODEL_TYPES.VLM3]: "green",
  [MODEL_TYPES.VLM4]: "green",
};

export function ModelLibraryList({
  models,
  defaultSlotMap,
  onCheck,
  onEdit,
  onDelete,
}: {
  models: ModelOption[];
  /** displayName -> slot keys this model occupies (drives the 默认 badge). */
  defaultSlotMap: Record<string, string[]>;
  onCheck: (displayName: string, modelType: ModelType) => void;
  onEdit: (model: ModelOption) => void;
  onDelete: (model: ModelOption) => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<ModelType | "all">("all");
  const [sourceFilter, setSourceFilter] = useState<ModelSource | "all">("all");
  const [page, setPage] = useState(1);

  const typeOptions = useMemo(() => {
    const list: { value: ModelType | "all"; label: string }[] = [
      {
        value: "all",
        label: t("model.filter.allTypes", { defaultValue: "全部类型" }),
      },
    ];
    const map: [ModelType, string][] = [
      [MODEL_TYPES.LLM, t("model.type.llm", { defaultValue: "大语言模型" })],
      [
        MODEL_TYPES.EMBEDDING,
        t("model.type.embedding", { defaultValue: "文本嵌入" }),
      ],
      [
        MODEL_TYPES.MULTI_EMBEDDING,
        t("model.type.multiEmbedding", { defaultValue: "多模态嵌入" }),
      ],
      [MODEL_TYPES.RERANK, t("model.type.rerank", { defaultValue: "重排" })],
      [
        MODEL_TYPES.VLM,
        t("model.type.imageUnderstanding", { defaultValue: "图像理解" }),
      ],
      [
        MODEL_TYPES.VLM2,
        t("model.type.imageGeneration", { defaultValue: "图像生成" }),
      ],
      [
        MODEL_TYPES.VLM3,
        t("model.type.videoUnderstanding", { defaultValue: "视频理解" }),
      ],
      [MODEL_TYPES.STT, t("model.type.stt", { defaultValue: "语音识别" })],
      [MODEL_TYPES.TTS, t("model.type.tts", { defaultValue: "语音合成" })],
    ];
    map.forEach(([v, l]) => list.push({ value: v, label: l }));
    return list;
  }, [t]);

  const sourceOptions = useMemo(() => {
    const list: { value: ModelSource | "all"; label: string }[] = [
      {
        value: "all",
        label: t("model.filter.allSources", {
          defaultValue: "全部服务商",
        }),
      },
    ];
    const map: [ModelSource, string][] = [
      [MODEL_SOURCES.MODELENGINE, "ModelEngine"],
      [MODEL_SOURCES.SILICON, "SiliconFlow"],
      [MODEL_SOURCES.OPENAI, "OpenAI"],
      [MODEL_SOURCES.OPENAI_API_COMPATIBLE, "OpenAI-API-Compatible"],
      [
        MODEL_SOURCES.CUSTOM,
        t("model.source.custom", { defaultValue: "自定义" }),
      ],
      [MODEL_SOURCES.DASHSCOPE, "DashScope"],
      [MODEL_SOURCES.TOKENPONY, "TokenPony"],
      [MODEL_SOURCES.VOLCENGINE, "VolcEngine"],
    ];
    map.forEach(([v, l]) => list.push({ value: v, label: l }));
    return list;
  }, [t]);

  const filtered = useMemo(() => {
    const kw = query.trim().toLowerCase();
    return models.filter((m) => {
      if (typeFilter !== "all" && m.type !== typeFilter) return false;
      if (sourceFilter !== "all" && m.source !== sourceFilter) return false;
      if (kw) {
        const hay = [m.name, m.displayName, m.apiUrl]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!hay.includes(kw)) return false;
      }
      return true;
    });
  }, [models, query, typeFilter, sourceFilter]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));

  // Reset to page 1 whenever the filters change, and clamp when the data
  // shrinks so the current page never overflows.
  useEffect(() => {
    setPage(1);
  }, [query, typeFilter, sourceFilter]);

  useEffect(() => {
    setPage((p) => Math.min(p, totalPages));
  }, [totalPages]);

  const start = (page - 1) * PAGE_SIZE;
  const paged = filtered.slice(start, start + PAGE_SIZE);

  return (
    <div className="flex flex-col gap-4">
      {/* ---------- Toolbar ---------- */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            allowClear
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("modelConfig.search.placeholder", {
              defaultValue: "搜索模型名 / 自定义名称 / API 地址",
            })}
            className="pl-9"
          />
        </div>
        <Select
          className="w-full sm:w-44"
          value={typeFilter}
          onChange={(v) => setTypeFilter(v as ModelType | "all")}
          options={typeOptions}
        />
        <Select
          className="w-full sm:w-44"
          value={sourceFilter}
          onChange={(v) => setSourceFilter(v as ModelSource | "all")}
          options={sourceOptions}
        />
      </div>

      {/* ---------- List ---------- */}
      <div className="overflow-hidden rounded-xl border">
        {/* Header (desktop only) */}
        <div className="hidden items-center gap-3 border-b bg-secondary/50 px-4 py-2.5 text-xs font-medium text-muted-foreground md:flex">
          <span className="w-52 shrink-0">
            {t("modelConfig.table.col.model", { defaultValue: "模型" })}
          </span>
          <span className="w-32 shrink-0">
            {t("modelConfig.table.col.type", { defaultValue: "类型" })}
          </span>
          <span className="w-28 shrink-0">
            {t("modelConfig.table.col.source", { defaultValue: "服务商" })}
          </span>
          <span className="flex-1">
            {t("modelConfig.table.col.connectStatus", {
              defaultValue: "状态",
            })}
          </span>
          <span className="w-28 shrink-0 text-right">
            {t("modelConfig.table.col.actions", { defaultValue: "操作" })}
          </span>
        </div>

        <div className="divide-y">
          {paged.map((m) => (
            <ModelRow
              key={`${m.id}-${m.displayName}-${m.type}`}
              model={m}
              isDefault={!!(defaultSlotMap[m.displayName] || []).length}
              onCheck={() => onCheck(m.displayName, m.type)}
              onEdit={() => onEdit(m)}
              onDelete={() => onDelete(m)}
            />
          ))}

          {filtered.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
              <PackageOpen className="size-8 text-muted-foreground/40" />
              <p className="text-sm text-muted-foreground">
                {models.length === 0
                  ? t("modelConfig.list.emptyLibrary", {
                      defaultValue: "模型库为空，先添加模型吧",
                    })
                  : t("modelConfig.list.emptyFilter", {
                      defaultValue: "未找到匹配的模型",
                    })}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ---------- Pagination ---------- */}
      {filtered.length > 0 && (
        <div className="flex flex-col items-center justify-between gap-3 sm:flex-row">
          <p className="text-xs text-muted-foreground">
            {t("modelConfig.pagination.pageInfo", {
              total: filtered.length,
              page,
              totalPages,
              defaultValue: `共 ${filtered.length} 个模型，第 ${page}/${totalPages} 页`,
            })}
          </p>
          <div className="flex items-center gap-1">
            <Button
              size="small"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              icon={<ChevronLeft className="size-4" />}
            >
              {t("modelConfig.pagination.prev", { defaultValue: "上一页" })}
            </Button>
            <div className="flex items-center gap-1">
              {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
                <Button
                  key={p}
                  size="small"
                  type={p === page ? "primary" : "text"}
                  className="min-w-8 px-0"
                  onClick={() => setPage(p)}
                >
                  {p}
                </Button>
              ))}
            </div>
            <Button
              size="small"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            >
              {t("modelConfig.pagination.next", { defaultValue: "下一页" })}
              <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function ModelRow({
  model,
  isDefault,
  onCheck,
  onEdit,
  onDelete,
}: {
  model: ModelOption;
  isDefault: boolean;
  onCheck: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const checking = model.connect_status === "detecting";
  const status = model.connect_status ?? "not_detected";
  const dotCls = STATUS_DOT_CLASS[status] ?? "bg-slate-300";
  const statusLabel = t(STATUS_LABEL_KEYS[status] ?? status, {
    defaultValue: STATUS_FALLBACK_LABELS[status] ?? status,
  });

  return (
    <div className="flex flex-col gap-3 px-4 py-3 transition-colors hover:bg-secondary/40 md:flex-row md:items-center md:gap-3">
      {/* Model name */}
      <div className="flex min-w-0 items-center gap-2 md:w-52 md:shrink-0">
        <div className="flex min-w-0 flex-col">
          <span className="truncate font-medium text-foreground">
            {model.displayName || model.name}
          </span>
          <span className="truncate font-mono text-xs text-muted-foreground">
            {model.name}
          </span>
        </div>
        {isDefault && (
          <Tag color="blue" className="m-0 shrink-0 text-[10px]">
            {t("modelConfig.list.defaultBadge", { defaultValue: "默认" })}
          </Tag>
        )}
      </div>

      {/* Type */}
      <div className="md:w-32 md:shrink-0">
        <Tag color={TYPE_BADGE_COLORS[model.type] || "default"} className="m-0">
          {t(`model.type.${TYPE_LABEL_KEY_MAP[model.type] ?? model.type}`, {
            defaultValue: model.type,
          })}
        </Tag>
      </div>

      {/* Source */}
      <div className="md:w-28 md:shrink-0">
        <span className="text-sm text-muted-foreground">{model.source}</span>
      </div>

      {/* Status */}
      <div className="flex flex-1 items-center gap-1.5">
        {checking ? (
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            {statusLabel}
          </span>
        ) : (
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className={`size-2 rounded-full ${dotCls}`} />
            {statusLabel}
          </span>
        )}
      </div>

      {/* Actions */}
      <div className="flex shrink-0 items-center gap-1 md:w-28 md:justify-end">
        <Tooltip
          title={t("modelConfig.list.checkConnectivity", {
            defaultValue: "检测连通性",
          })}
        >
          <Button
            size="small"
            type="text"
            icon={<ShieldCheck className="size-4" />}
            disabled={checking}
            onClick={onCheck}
          />
        </Tooltip>
        <Tooltip title={t("common.edit", { defaultValue: "编辑" })}>
          <Button
            size="small"
            type="text"
            icon={<Pencil className="size-4" />}
            onClick={onEdit}
          />
        </Tooltip>
        <Tooltip title={t("common.delete", { defaultValue: "删除" })}>
          <Button
            size="small"
            type="text"
            danger
            icon={<Trash2 className="size-4" />}
            onClick={onDelete}
          />
        </Tooltip>
      </div>
    </div>
  );
}
