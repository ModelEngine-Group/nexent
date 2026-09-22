"use client";

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Pencil,
  Trash2,
  Link2,
  ChevronDown,
  ChevronRight,
  Check,
  Loader2,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import { ModelOption, ModelSource } from "@/types/modelConfig";

/**
 * v2.6.1 redesign (v0 design): batch manage models by connection.
 *
 * Models imported from the same provider share one "connection" (source +
 * API key + base URL). The dialog groups the library by connection so an
 * operator can rotate a key or move a whole group to another endpoint in
 * one action, or remove a batch of models at once. Built on the project's
 * shadcn/ui primitives to match the v0 aesthetic.
 *
 * Backend contract: each member is updated with a partial payload
 * (api_key + base_url only) via the single-model update endpoint, and
 * deletes go through the existing per-model delete endpoint. Default-slot
 * cleanup for deleted models is handled by the caller.
 */

export interface ConnectionGroup {
  key: string;
  source: ModelSource;
  apiKey: string;
  apiUrl: string;
  models: ModelOption[];
}

/** Normalize a URL for connection grouping:
 *  1. Strip the /embeddings suffix (embedding models carry it, protocol
 *     detail not a different endpoint).
 *  2. Strip trailing slashes (v1/ and v1 are the same endpoint).
 */
function normalizeUrlForGrouping(url: string): string {
  return url.replace(/\/embeddings\/?$/, "").replace(/\/+$/, "");
}

export function groupByConnection(models: ModelOption[]): ConnectionGroup[] {
  const map = new Map<string, ConnectionGroup>();
  for (const m of models) {
    const key = `${m.source}|${m.apiKey}|${normalizeUrlForGrouping(m.apiUrl ?? "")}`;
    let group = map.get(key);
    if (!group) {
      group = {
        key,
        source: m.source,
        apiKey: m.apiKey ?? "",
        apiUrl: m.apiUrl ?? "",
        models: [],
      };
      map.set(key, group);
    }
    group.models.push(m);
  }
  return Array.from(map.values());
}

// Raw type ids -> the semantic i18n keys used across the app (same mapping
// as ModelLibraryList).
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

export function ModelManagerDialog({
  open,
  mode,
  models,
  onClose,
  onUpdateGroup,
  onDeleteModels,
  updating,
  deleting,
}: {
  open: boolean;
  mode: "editGroup" | "deleteGroup";
  models: ModelOption[];
  onClose: () => void;
  onUpdateGroup: (
    group: ConnectionGroup,
    patch: { apiKey: string; url: string }
  ) => Promise<void>;
  onDeleteModels: (targets: ModelOption[]) => Promise<void>;
  updating?: boolean;
  deleting?: boolean;
}) {
  const { t } = useTranslation();
  const groups = useMemo(() => groupByConnection(models), [models]);

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="flex max-h-[85vh] w-[calc(100vw-2rem)] flex-col gap-0 overflow-hidden p-0 sm:max-w-3xl">
        <DialogHeader className="border-b px-6 py-4">
          <DialogTitle className="text-base">
            {mode === "editGroup"
              ? t("modelConfig.batchEdit.title", { defaultValue: "批量修改" })
              : t("modelConfig.batchDelete.title", {
                  defaultValue: "批量删除",
                })}
          </DialogTitle>
          <DialogDescription>
            {mode === "editGroup"
              ? t("modelConfig.batchEdit.description", {
                  defaultValue:
                    "按连接（相同服务商 + API Key + Base URL）分组，修改将应用到该连接下全部模型。",
                })
              : t("modelConfig.batchDelete.description", {
                  defaultValue:
                    "可删除整条连接（含其下全部模型），也可仅勾选部分模型删除。",
                })}
          </DialogDescription>
        </DialogHeader>
        {mode === "editGroup" ? (
          <EditGroupContent
            groups={groups}
            onUpdateGroup={onUpdateGroup}
            updating={!!updating}
            onDone={onClose}
          />
        ) : (
          <DeleteGroupContent
            groups={groups}
            onDeleteModels={onDeleteModels}
            deleting={!!deleting}
            onDone={onClose}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

/* ------------------------------ 批量修改 ------------------------------ */

function EditGroupContent({
  groups,
  onUpdateGroup,
  updating,
  onDone,
}: {
  groups: ConnectionGroup[];
  onUpdateGroup: (
    group: ConnectionGroup,
    patch: { apiKey: string; url: string }
  ) => Promise<void>;
  updating: boolean;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-6 py-5">
        {groups.map((g) => {
          const isEditing = editingKey === g.key;
          const isOpen = !!expanded[g.key];
          return (
            <div key={g.key} className="overflow-hidden rounded-xl border">
              <div className="flex items-start justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Badge variant="secondary" className="text-xs font-medium">
                      {g.source}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {t("modelConfig.batchEdit.modelCount", {
                        count: g.models.length,
                        defaultValue: `${g.models.length} 个模型`,
                      })}
                    </span>
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1 truncate font-mono">
                      <Link2 className="size-3" />
                      {g.apiUrl || "—"}
                    </span>
                  </div>
                </div>
                {!isEditing && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="shrink-0"
                    onClick={() => setEditingKey(g.key)}
                  >
                    <Pencil className="size-4" />
                    {t("common.edit", { defaultValue: "修改" })}
                  </Button>
                )}
              </div>

              <button
                type="button"
                onClick={() =>
                  setExpanded((s) => ({ ...s, [g.key]: !s[g.key] }))
                }
                className="flex w-full items-center gap-1 border-t px-4 py-2 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                {isOpen ? (
                  <ChevronDown className="size-3.5" />
                ) : (
                  <ChevronRight className="size-3.5" />
                )}
                {isOpen
                  ? t("modelConfig.batchEdit.collapse", {
                      defaultValue: "收起",
                    })
                  : t("modelConfig.batchEdit.expand", {
                      defaultValue: "查看下属模型",
                    })}
              </button>
              {isOpen && (
                <ul className="divide-y border-t">
                  {g.models.map((m) => (
                    <li
                      key={`${m.id}-${m.displayName}`}
                      className="px-4 py-2 text-sm"
                    >
                      <span className="font-medium">{m.displayName}</span>
                      <span className="ml-2 font-mono text-xs text-muted-foreground">
                        {m.name}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {isEditing && (
                <EditGroupForm
                  group={g}
                  saving={updating}
                  onSave={async (patch) => {
                    await onUpdateGroup(g, patch);
                    setEditingKey(null);
                  }}
                  onCancel={() => setEditingKey(null)}
                />
              )}
            </div>
          );
        })}
        {groups.length === 0 && (
          <p className="py-12 text-center text-sm text-muted-foreground">
            {t("modelConfig.list.emptyLibrary", { defaultValue: "模型库为空" })}
          </p>
        )}
      </div>

      <div className="flex justify-end border-t px-6 py-4">
        <Button onClick={onDone}>
          {t("common.done", { defaultValue: "完成" })}
        </Button>
      </div>
    </div>
  );
}

function EditGroupForm({
  group,
  saving,
  onSave,
  onCancel,
}: {
  group: ConnectionGroup;
  saving: boolean;
  onSave: (patch: { apiKey: string; url: string }) => Promise<void>;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [apiKey, setApiKey] = useState(group.apiKey);
  const [url, setUrl] = useState(group.apiUrl);

  return (
    <div className="space-y-4 border-t bg-secondary/30 p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Pencil className="size-4 text-primary" />
        {t("modelConfig.batchEdit.editingTitle", {
          count: group.models.length,
          defaultValue: `修改连接（${group.models.length} 个模型）`,
        })}
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor={`batch-key-${group.key}`}>
            {t("modelConfig.batchEdit.apiKey", { defaultValue: "API Key" })}
          </Label>
          <Input
            id={`batch-key-${group.key}`}
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-..."
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`batch-url-${group.key}`}>
            {t("modelConfig.batchEdit.baseUrl", { defaultValue: "Base URL" })}
          </Label>
          <Input
            id={`batch-url-${group.key}`}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://api.example.com/v1"
          />
        </div>
      </div>
      <div className="rounded-lg bg-background px-3 py-2 text-xs text-muted-foreground">
        {t("modelConfig.batchEdit.applyHint", {
          count: group.models.length,
          defaultValue: `以下修改将应用到该连接下全部 ${group.models.length} 个模型：`,
        })}
        <span className="ml-1 font-mono text-foreground">
          {group.models.map((m) => m.name).join("、")}
        </span>
      </div>
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onCancel}>
          {t("common.cancel", { defaultValue: "取消" })}
        </Button>
        <Button
          size="sm"
          disabled={!url.trim() || saving}
          onClick={() => onSave({ apiKey: apiKey.trim(), url: url.trim() })}
        >
          {saving && <Loader2 className="size-4 animate-spin" />}
          {t("common.save", { defaultValue: "保存修改" })}
        </Button>
      </div>
    </div>
  );
}

/* ------------------------------ 批量删除 ------------------------------ */

function DeleteGroupContent({
  groups,
  onDeleteModels,
  deleting,
  onDone,
}: {
  groups: ConnectionGroup[];
  onDeleteModels: (targets: ModelOption[]) => Promise<void>;
  deleting: boolean;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const modelKey = (m: ModelOption) => `${m.id}-${m.displayName}-${m.type}`;
  const selectedModels = useMemo(
    () =>
      groups
        .flatMap((g) => g.models)
        .filter((m) => selectedKeys.has(modelKey(m))),
    [groups, selectedKeys]
  );

  function toggleModel(m: ModelOption) {
    setSelectedKeys((s) => {
      const next = new Set(s);
      const k = modelKey(m);
      if (next.has(k)) {
        next.delete(k);
      } else {
        next.add(k);
      }
      return next;
    });
  }

  function toggleGroup(models: ModelOption[], on: boolean) {
    setSelectedKeys((s) => {
      const next = new Set(s);
      models.forEach((m) =>
        on ? next.add(modelKey(m)) : next.delete(modelKey(m))
      );
      return next;
    });
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-6 py-5">
        {groups.map((g) => {
          const keys = g.models.map(modelKey);
          const selCount = keys.filter((k) => selectedKeys.has(k)).length;
          const all = selCount === keys.length;
          const some = selCount > 0 && !all;
          return (
            <div key={g.key} className="overflow-hidden rounded-xl border">
              <div className="flex items-start justify-between gap-3 border-b bg-secondary/30 px-4 py-3">
                <button
                  type="button"
                  className="flex min-w-0 items-start gap-3 text-left"
                  onClick={() => toggleGroup(g.models, !all)}
                >
                  <span
                    className={cn(
                      "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded border",
                      all
                        ? "border-destructive bg-destructive text-white"
                        : some
                          ? "border-destructive bg-destructive/20"
                          : "border-input"
                    )}
                  >
                    {all && <Check className="size-3" />}
                    {some && (
                      <span className="size-2 rounded-sm bg-destructive" />
                    )}
                  </span>
                  <span className="min-w-0">
                    <span className="flex items-center gap-2">
                      <Badge
                        variant="secondary"
                        className="border-0 text-xs font-medium"
                      >
                        {g.source}
                      </Badge>
                      <span className="text-xs text-muted-foreground">
                        {t("modelConfig.batchEdit.modelCount", {
                          count: g.models.length,
                          defaultValue: `${g.models.length} 个模型`,
                        })}
                      </span>
                    </span>
                    <span className="mt-1.5 flex items-center gap-x-4 text-xs text-muted-foreground">
                      <span className="truncate font-mono">{g.apiUrl}</span>
                    </span>
                  </span>
                </button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="shrink-0 text-destructive hover:text-destructive"
                  onClick={() => toggleGroup(g.models, true)}
                >
                  <Trash2 className="size-4" />
                  {t("modelConfig.batchDelete.selectGroup", {
                    defaultValue: "全选",
                  })}
                </Button>
              </div>
              <button
                type="button"
                onClick={() =>
                  setExpanded((s) => ({ ...s, [g.key]: !s[g.key] }))
                }
                className="flex w-full items-center gap-1 border-t px-4 py-2 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                {expanded[g.key] ? (
                  <ChevronDown className="size-3.5" />
                ) : (
                  <ChevronRight className="size-3.5" />
                )}
                {expanded[g.key]
                  ? t("modelConfig.batchEdit.collapse", {
                      defaultValue: "收起",
                    })
                  : t("modelConfig.batchEdit.expand", {
                      defaultValue: "查看下属模型",
                    })}
              </button>
              {expanded[g.key] && (
                <ul className="divide-y">
                  {g.models.map((m) => {
                    const on = selectedKeys.has(modelKey(m));
                    return (
                      <li key={modelKey(m)}>
                        <button
                          type="button"
                          onClick={() => toggleModel(m)}
                          className={cn(
                            "flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left transition-colors hover:bg-secondary/40",
                            on && "bg-secondary/30"
                          )}
                        >
                          <span className="flex min-w-0 items-center gap-3">
                            <span
                              className={cn(
                                "flex size-4 shrink-0 items-center justify-center rounded border",
                                on
                                  ? "border-destructive bg-destructive text-white"
                                  : "border-input"
                              )}
                            >
                              {on && <Check className="size-3" />}
                            </span>
                            <span className="truncate font-medium">
                              {m.displayName}
                            </span>
                          </span>
                          <span className="shrink-0 text-xs text-muted-foreground">
                            {t(
                              `model.type.${TYPE_LABEL_KEY_MAP[m.type] ?? m.type}`,
                              {
                                defaultValue: m.type,
                              }
                            )}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        })}
        {groups.length === 0 && (
          <p className="py-12 text-center text-sm text-muted-foreground">
            {t("modelConfig.list.emptyLibrary", { defaultValue: "模型库为空" })}
          </p>
        )}
      </div>

      <div className="flex items-center justify-between border-t px-6 py-4">
        <span className="text-sm text-muted-foreground">
          {t("modelConfig.batchDelete.selectedCount", {
            count: selectedModels.length,
            defaultValue: `已选 ${selectedModels.length} 个模型`,
          })}
        </span>
        <div className="flex gap-2">
          <Button variant="outline" onClick={onDone}>
            {t("common.cancel", { defaultValue: "取消" })}
          </Button>
          <Button
            variant="destructive"
            disabled={selectedModels.length === 0 || deleting}
            onClick={async () => {
              await onDeleteModels(selectedModels);
              onDone();
            }}
          >
            {deleting && <Loader2 className="size-4 animate-spin" />}
            <Trash2 className="size-4" />
            {t("modelConfig.batchDelete.confirm", {
              count: selectedModels.length,
              defaultValue: `删除 ${selectedModels.length} 个模型`,
            })}
          </Button>
        </div>
      </div>
    </div>
  );
}
