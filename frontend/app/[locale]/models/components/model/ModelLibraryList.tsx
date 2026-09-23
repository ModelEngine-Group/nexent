"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
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

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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

import { MODEL_SOURCES } from "@/const/modelConfig";
import { ModelOption, ModelType, ModelSource } from "@/types/modelConfig";
import {
  STATUS_DOT_CLASS,
  TYPE_BADGE_CLASS,
  TYPE_LABEL_KEY_MAP,
} from "./modelTypeUi";

/**
 * v2.6.1 redesign (v0 design): the model library as a custom list built on
 * the project's shadcn/ui primitives — quiet table header, lightweight rows
 * (name + default badge, type badge, provider, connectivity dot, icon
 * actions with tooltips) and custom pagination.
 */

const PAGE_SIZE = 8;

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

  const typeOptions: ModelType[] = useMemo(
    () => Object.keys(TYPE_LABEL_KEY_MAP) as ModelType[],
    []
  );

  const sourceOptions: ModelSource[] = useMemo(
    () => Object.values(MODEL_SOURCES),
    []
  );

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
    <div className="flex h-full min-h-0 flex-1 flex-col gap-4">
      {/* ---------- Toolbar (fixed) ---------- */}
      <div className="flex shrink-0 flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("modelConfig.search.placeholder", {
              defaultValue: "搜索模型名 / 自定义名称 / API 地址",
            })}
            className="pl-9"
          />
        </div>
        <Select
          value={typeFilter}
          onValueChange={(v) => setTypeFilter(v as ModelType | "all")}
        >
          <SelectTrigger className="w-full sm:w-44">
            <SelectValue
              placeholder={t("model.filter.allTypes", {
                defaultValue: "全部类型",
              })}
            />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">
              {t("model.filter.allTypes", { defaultValue: "全部类型" })}
            </SelectItem>
            {typeOptions.map((v) => (
              <SelectItem key={v} value={v}>
                {t(`model.type.${TYPE_LABEL_KEY_MAP[v] ?? v}`, {
                  defaultValue: v,
                })}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={sourceFilter}
          onValueChange={(v) => setSourceFilter(v as ModelSource | "all")}
        >
          <SelectTrigger className="w-full sm:w-44">
            <SelectValue
              placeholder={t("model.filter.allSources", {
                defaultValue: "全部服务商",
              })}
            />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">
              {t("model.filter.allSources", { defaultValue: "全部服务商" })}
            </SelectItem>
            {sourceOptions.map((v) => (
              <SelectItem key={v} value={v}>
                {v}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* ---------- List (internal scroll area) ---------- */}
      <div className="min-h-[240px] flex-1 overflow-y-auto rounded-xl border">
        {/* Header (desktop only) */}
        <div className="hidden items-center gap-3 border-b bg-secondary/50 px-4 py-2.5 text-xs font-medium text-muted-foreground md:flex">
          <span className="w-64 shrink-0">
            {t("modelConfig.table.col.model", { defaultValue: "模型" })}
          </span>
          <span className="w-40 shrink-0">
            {t("modelConfig.table.col.type", { defaultValue: "类型" })}
          </span>
          <span className="w-32 shrink-0">
            {t("modelConfig.table.col.source", { defaultValue: "服务商" })}
          </span>
          <span className="flex-1">
            {t("modelConfig.table.col.connectStatus", { defaultValue: "状态" })}
          </span>
          <span className="w-32 shrink-0 text-right">
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

      {/* ---------- Pagination (fixed) ---------- */}
      {filtered.length > 0 && (
        <div className="flex shrink-0 flex-col items-center justify-between gap-3 sm:flex-row">
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
              size="sm"
              variant="outline"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              <ChevronLeft className="size-4" />
              {t("modelConfig.pagination.prev", { defaultValue: "上一页" })}
            </Button>
            <div className="flex items-center gap-1">
              {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
                <Button
                  key={p}
                  size="icon"
                  variant={p === page ? "default" : "ghost"}
                  className="size-8 text-xs"
                  onClick={() => setPage(p)}
                >
                  {p}
                </Button>
              ))}
            </div>
            <Button
              size="sm"
              variant="outline"
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
      <div className="flex min-w-0 items-center gap-2 md:w-64 md:shrink-0">
        <div className="flex min-w-0 flex-col">
          <span className="flex min-w-0 items-center gap-2">
            <span className="truncate font-medium text-foreground">
              {model.displayName || model.name}
            </span>
            {isDefault && (
              <Badge
                variant="secondary"
                className="shrink-0 bg-primary/10 px-1.5 text-[10px] font-normal text-primary hover:bg-primary/10"
              >
                {t("modelConfig.list.defaultBadge", {
                  defaultValue: "默认",
                })}
              </Badge>
            )}
          </span>
          <span className="truncate font-mono text-xs text-muted-foreground">
            {model.name}
          </span>
        </div>
      </div>

      {/* Type */}
      <div className="md:w-40 md:shrink-0">
        <Badge
          variant="secondary"
          className={cn(
            "border-0 text-xs font-normal",
            TYPE_BADGE_CLASS[model.type]
          )}
        >
          {t(`model.type.${TYPE_LABEL_KEY_MAP[model.type] ?? model.type}`, {
            defaultValue: model.type,
          })}
        </Badge>
      </div>

      {/* Source */}
      <div className="md:w-32 md:shrink-0">
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
      <div className="flex shrink-0 items-center gap-0.5 md:w-32 md:justify-end">
        <RowAction
          label={t("modelConfig.list.checkConnectivity", {
            defaultValue: "检测连通性",
          })}
          onClick={onCheck}
          disabled={checking}
        >
          <ShieldCheck className="size-4" />
        </RowAction>
        <RowAction
          label={t("common.edit", { defaultValue: "编辑" })}
          onClick={onEdit}
        >
          <Pencil className="size-4" />
        </RowAction>
        <RowAction
          label={t("common.delete", { defaultValue: "删除" })}
          onClick={onDelete}
          destructive
        >
          <Trash2 className="size-4" />
        </RowAction>
      </div>
    </div>
  );
}

function RowAction({
  label,
  onClick,
  disabled,
  destructive,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  destructive?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          size="icon"
          variant="ghost"
          disabled={disabled}
          onClick={onClick}
          className={cn(
            "size-8",
            destructive && "text-destructive hover:text-destructive"
          )}
        >
          {children}
          <span className="sr-only">{label}</span>
        </Button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}
