// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { ResourcePickerPresentation } from "@/features/workbench/components/ResourcePickerPresentation";
import { ResourceTagFilter } from "@/features/workbench/components/ResourceTagFilter";
import { useResourceTags } from "@/features/workbench/hooks/useResourceTags";

import { ResourceSelectionActions } from "@/features/workbench/components/ResourceSelectionActions";

import { SelectedResourceTags } from "@/features/workbench/components/SelectedResourceTags";

import {
  ResourceSelectionGrid,
  RESOURCE_SELECTION_AREA_CLASS,
} from "@/features/workbench/components/ResourceSelectionGrid";
import {
  ResourcePagination,
  resourcePage,
} from "@/features/workbench/components/ResourcePagination";

import { useEffect, useMemo, useRef, useState, type FC } from "react";
import { useTranslation } from "react-i18next";
import { useRouter } from "next/navigation";
import {
  Alert,
  Button,
  Checkbox,
  Empty,
  Input,
  Segmented,
  Spin,
  message,
} from "antd";
import { ChevronDown, ChevronLeft, ChevronRight, FileText } from "lucide-react";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { useGroupList } from "@/hooks/group/useGroupList";
import type { KnowledgeBase } from "@/types/knowledgeBase";
import type {
  AidpFileScope,
  ConversationKnowledgeScope,
  KnowledgeCapabilities,
  KnowledgeScopeEffectivePreview,
} from "@/types/knowledgeScope";
import {
  DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE,
  EMPTY_AIDP_FILE_SCOPE,
  getAidpFileScope,
  withAidpFileScope,
} from "@/types/knowledgeScope";
import {
  FILE_SCOPE_BROWSE_PAGE_SIZE,
  useFileScopeCatalog,
  type FileScopeFile,
  type FileScopeGroupState,
  type FileScopeKnowledgeBase,
} from "./useFileScopeCatalog";
import { ResourceCard } from "@/features/workbench";
import { KnowledgeSelectionList } from "@/components/resource-picker/KnowledgeSelectionList";
import { WorkbenchResourceDrawer } from "@/features/workbench/components/WorkbenchResourceDrawer";
import { RESOURCE_PAGE_SIZE } from "@/features/workbench/components/ResourcePagination";
import { RestoreDefaultsButton } from "@/features/workbench/components/RestoreDefaultsButton";

interface ConversationKnowledgeScopeModalProps {
  open: boolean;
  presentation?: "modal" | "drawer";
  disabled?: boolean;
  value: ConversationKnowledgeScope | null;
  capabilities: KnowledgeCapabilities | null;
  onCancel: () => void;
  onConfirm: (
    scope: ConversationKnowledgeScope,
    preview: KnowledgeScopeEffectivePreview
  ) => Promise<void> | void;
}

const copyScope = (
  value: ConversationKnowledgeScope | null
): ConversationKnowledgeScope =>
  JSON.parse(
    JSON.stringify({
      schema_version:
        (value || DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE).schema_version ?? 1,
      local: (value || DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE).local,
      aidp: (value || DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE).aidp,
    })
  ) as ConversationKnowledgeScope;

const fileScopeForSelection = (
  scope: ConversationKnowledgeScope,
  selectedIds: string[] | null
): AidpFileScope => {
  const current = scope.aidp.file_scope;
  if (!current || current.mode !== "selected") return EMPTY_AIDP_FILE_SCOPE;
  const files =
    selectedIds === null
      ? current.files
      : current.files.filter((file) => selectedIds.includes(file.kds_id));
  return files.length > 0 ? { mode: "selected", files } : EMPTY_AIDP_FILE_SCOPE;
};

const normalizeScopeForSource = (
  value: ConversationKnowledgeScope | null,
  source: "local" | "aidp" | null
): ConversationKnowledgeScope => {
  const scope = copyScope(value);
  if (!source) return scope;
  if (scope.local.mode === "disabled" && scope.aidp.mode === "disabled") {
    return scope;
  }
  if (source === "local" && scope.local.mode === "inherit") {
    return withAidpFileScope(
      {
        schema_version: 1,
        local: { mode: "inherit", knowledge_ids: [] },
        aidp: { mode: "disabled", kds_ids: [] },
      },
      EMPTY_AIDP_FILE_SCOPE
    );
  }
  if (source === "aidp" && scope.aidp.mode === "inherit") {
    return withAidpFileScope(
      {
        ...scope,
        local: { mode: "disabled", knowledge_ids: [] },
        aidp: { mode: "inherit", kds_ids: [] },
      },
      fileScopeForSelection(scope, null)
    );
  }
  if (source === "local" && scope.local.mode === "override") {
    return withAidpFileScope(
      {
        ...scope,
        aidp: { mode: "disabled", kds_ids: [] },
      },
      EMPTY_AIDP_FILE_SCOPE
    );
  }
  if (source === "aidp" && scope.aidp.mode === "override") {
    return withAidpFileScope(
      {
        ...scope,
        local: { mode: "disabled", knowledge_ids: [] },
      },
      fileScopeForSelection(scope, scope.aidp.kds_ids)
    );
  }
  return withAidpFileScope(
    {
      schema_version: 1,
      local: { mode: "disabled", knowledge_ids: [] },
      aidp: { mode: "disabled", kds_ids: [] },
    },
    EMPTY_AIDP_FILE_SCOPE
  );
};

export const ConversationKnowledgeScopeModal: FC<
  ConversationKnowledgeScopeModalProps
> = ({
  open,
  value,
  capabilities,
  onCancel,
  onConfirm,
  presentation = "modal",
  disabled = false,
}) => {
  const { t } = useTranslation();
  const router = useRouter();
  const { enableAidpKnowledge, isDeploymentReady } = useDeployment();
  const { user } = useAuthorizationContext();
  const { data: groupListData } = useGroupList(user?.tenantId ?? null);
  const groupNameById = useMemo(
    () =>
      new Map(
        (groupListData?.groups ?? []).map((group) => [
          group.group_id,
          group.group_name,
        ])
      ),
    [groupListData]
  );
  const configuredSource: "local" | "aidp" | null = !isDeploymentReady
    ? null
    : enableAidpKnowledge
      ? "aidp"
      : "local";
  const [draft, setDraft] = useState<ConversationKnowledgeScope>(() =>
    normalizeScopeForSource(value, configuredSource)
  );
  const [localKnowledgeBases, setLocalKnowledgeBases] = useState<
    KnowledgeBase[]
  >([]);
  const [aidpKnowledgeBases, setAidpKnowledgeBases] = useState<KnowledgeBase[]>(
    []
  );
  const [listError, setListError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [initialSelectedIds, setInitialSelectedIds] = useState<string[]>([]);
  const [initialSelectionWasFiltered, setInitialSelectionWasFiltered] =
    useState(false);
  const [defaultSelectedIds, setDefaultSelectedIds] = useState<string[]>([]);
  const [selectionTouched, setSelectionTouched] = useState(false);
  const [restoreDefaultClicked, setRestoreDefaultClicked] = useState(false);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(RESOURCE_PAGE_SIZE);
  const initialScopeMode: "kb" | "files" =
    value?.aidp.file_scope?.mode === "selected" ? "files" : "kb";
  const [scopeMode, setScopeMode] = useState<"kb" | "files">(initialScopeMode);
  const [expandedFileGroups, setExpandedFileGroups] = useState<Set<string>>(
    new Set()
  );
  const [modeInputs, setModeInputs] = useState({ open, initialScopeMode });
  if (
    modeInputs.open !== open ||
    modeInputs.initialScopeMode !== initialScopeMode
  ) {
    setModeInputs({ open, initialScopeMode });
    if (open) setScopeMode(initialScopeMode);
  }
  const tags = useResourceTags(
    open && presentation === "drawer" && configuredSource === "local",
    "knowledge_base",
    localKnowledgeBases.map((kb) => String(kb.id))
  );
  const catalogRequest = useMemo(
    () => ({ open, value, source: configuredSource, capabilities, t }),
    [open, value, configuredSource, capabilities, t]
  );
  const [refreshRevision, setRefreshRevision] = useState(0);
  const initializedCatalogRequest = useRef<typeof catalogRequest | null>(null);
  const catalogLoadRequest = useMemo(
    () => ({ catalogRequest, refreshRevision }),
    [catalogRequest, refreshRevision]
  );
  const [settledCatalogRequest, setSettledCatalogRequest] = useState<
    typeof catalogLoadRequest | null
  >(null);
  const loading =
    open &&
    Boolean(configuredSource) &&
    settledCatalogRequest !== catalogLoadRequest;
  const [previousInputs, setPreviousInputs] = useState({
    open,
    search,
    enableAidpKnowledge,
    catalogRequest,
  });
  // Guard input-driven resets so children never render stale picker state.
  if (
    previousInputs.open !== open ||
    previousInputs.search !== search ||
    previousInputs.enableAidpKnowledge !== enableAidpKnowledge ||
    previousInputs.catalogRequest !== catalogRequest
  ) {
    setPreviousInputs({ open, search, enableAidpKnowledge, catalogRequest });
    if (
      previousInputs.open !== open ||
      previousInputs.search !== search ||
      previousInputs.enableAidpKnowledge !== enableAidpKnowledge
    )
      setPage(1);
    if (
      open &&
      configuredSource &&
      previousInputs.catalogRequest !== catalogRequest
    ) {
      setDraft(normalizeScopeForSource(value, configuredSource));
      setInitialSelectionWasFiltered(false);
      setSelectionTouched(false);
      setRestoreDefaultClicked(false);
      setSearch("");
      setListError(false);
    }
  }
  useEffect(() => {
    const { catalogRequest } = catalogLoadRequest;
    const configuredSource = catalogRequest.source;
    if (!open || !configuredSource) return;
    const { value, capabilities, t } = catalogRequest;
    const normalized = normalizeScopeForSource(value, configuredSource);
    let cancelled = false;
    Promise.all([
      configuredSource === "local"
        ? knowledgeBaseService.getKnowledgeBasesInfo(
            false,
            false,
            null,
            null,
            undefined,
            { strict: true }
          )
        : Promise.resolve({ knowledgeBases: [] }),
      configuredSource === "aidp"
        ? knowledgeBaseService.getAidpKnowledgeBasesAll()
        : Promise.resolve({ value: [] }),
    ])
      .then(([localResult, aidpResult]) => {
        if (cancelled) return;
        const localItems = (localResult.knowledgeBases || []).filter(
          (kb: KnowledgeBase) =>
            kb.knowledge_id !== undefined && kb.knowledge_id !== null
        );
        const aidpItems =
          knowledgeBaseService.mapAidpKnowledgeBasesToKnowledgeBases(
            aidpResult.value || []
          );
        setLocalKnowledgeBases(localItems);
        setAidpKnowledgeBases(aidpItems);
        if (initializedCatalogRequest.current === catalogRequest) return;
        initializedCatalogRequest.current = catalogRequest;
        const availableIds = new Set(
          configuredSource === "local"
            ? localItems.map((kb: KnowledgeBase) => String(kb.knowledge_id))
            : aidpItems.map((kb: KnowledgeBase) => String(kb.id))
        );
        const defaults =
          (configuredSource
            ? capabilities?.sources[configuredSource].default_knowledge_ids
            : []
          )?.filter((id) => availableIds.has(String(id))) ?? [];
        const selected =
          configuredSource === "local"
            ? normalized.local.mode === "override"
              ? normalized.local.knowledge_ids
              : normalized.local.mode === "disabled"
                ? []
                : defaults
            : configuredSource === "aidp"
              ? normalized.aidp.mode === "override"
                ? normalized.aidp.kds_ids
                : normalized.aidp.mode === "disabled"
                  ? []
                  : defaults
              : [];
        const visibleSelected = selected.filter((id) =>
          availableIds.has(String(id))
        );
        setDefaultSelectedIds(defaults.map(String));
        setInitialSelectedIds(visibleSelected.map(String));
        setInitialSelectionWasFiltered(
          selected.length !== visibleSelected.length
        );
        setDraft(
          configuredSource === "local"
            ? {
                ...normalized,
                local: {
                  mode: "override",
                  knowledge_ids: visibleSelected.map(String),
                },
                aidp: { mode: "disabled", kds_ids: [] },
              }
            : configuredSource === "aidp"
              ? {
                  ...normalized,
                  local: { mode: "disabled", knowledge_ids: [] },
                  aidp: {
                    mode: "override",
                    kds_ids: visibleSelected.map(String),
                    file_scope: normalized.aidp.file_scope,
                  },
                }
              : normalized
        );
      })
      .catch(() => {
        if (!cancelled) {
          setListError(true);
          message.error(t("chat.knowledgeScope.listLoadFailed"));
        }
      })
      .finally(() => {
        if (!cancelled) setSettledCatalogRequest(catalogLoadRequest);
      });
    return () => {
      cancelled = true;
    };
  }, [open, catalogLoadRequest]);

  const localOptions = useMemo(
    () =>
      localKnowledgeBases
        .filter(
          (kb) => kb.knowledge_id !== undefined && kb.knowledge_id !== null
        )
        .map((kb) => ({
          label: kb.display_name || kb.name,
          value: String(kb.knowledge_id),
        })),
    [localKnowledgeBases]
  );
  const aidpOptions = useMemo(
    () =>
      aidpKnowledgeBases.map((kb) => ({
        label: kb.display_name || kb.name,
        value: kb.id,
      })),
    [aidpKnowledgeBases]
  );

  const fileScopeKnowledgeBases = useMemo(() => {
    if (configuredSource !== "aidp") return [];
    const available = new Set(aidpKnowledgeBases.map((kb) => String(kb.id)));
    const configured = capabilities?.sources.aidp.default_knowledge_ids ?? [];
    const fallback = draft.aidp.kds_ids;
    const ids = (configured.length > 0 ? configured : fallback)
      .map(String)
      .filter((id) => available.has(id));
    return Array.from(new Set(ids)).map((id) => {
      const kb = aidpKnowledgeBases.find(
        (candidate) => String(candidate.id) === id
      );
      return {
        id,
        name: kb ? kb.display_name || kb.name : id,
      };
    });
  }, [aidpKnowledgeBases, capabilities, configuredSource, draft.aidp.kds_ids]);

  const fileCatalog = useFileScopeCatalog({
    knowledgeBases: fileScopeKnowledgeBases,
    enabled: open && scopeMode === "files" && configuredSource === "aidp",
    searchTerm: scopeMode === "files" ? search : "",
  });

  const selectedFileScope = getAidpFileScope(draft);
  const selectedFiles = selectedFileScope.files;
  const selectedFileKeys = useMemo(
    () =>
      new Set(selectedFiles.map((file) => `${file.kds_id}:${file.file_uuid}`)),
    [selectedFiles]
  );
  const duplicatedSelectedNames = useMemo(() => {
    const counts = new Map<string, number>();
    selectedFiles.forEach((file) => {
      const name = file.file_name || file.file_uuid;
      counts.set(name, (counts.get(name) ?? 0) + 1);
    });
    return new Set(
      Array.from(counts.entries())
        .filter(([, count]) => count > 1)
        .map(([name]) => name)
    );
  }, [selectedFiles]);
  const selectedCountByGroup = useMemo(() => {
    const counts = new Map<string, number>();
    selectedFiles.forEach((file) => {
      const id = String(file.kds_id);
      counts.set(id, (counts.get(id) ?? 0) + 1);
    });
    return counts;
  }, [selectedFiles]);
  const firstFileGroupId = fileScopeKnowledgeBases[0]?.id ?? "";
  const fileEntryKey =
    open && scopeMode === "files" && configuredSource === "aidp"
      ? `${open}:${firstFileGroupId}`
      : "";
  const [fileEntry, setFileEntry] = useState({ key: "", firstId: "" });
  if (fileEntry.key !== fileEntryKey) {
    setFileEntry({ key: fileEntryKey, firstId: firstFileGroupId });
    setExpandedFileGroups(
      fileEntryKey && firstFileGroupId ? new Set([firstFileGroupId]) : new Set()
    );
  }
  const toggleFileGroup = (id: string) => {
    if (disabled || saving) return;
    const isExpanded = expandedFileGroups.has(id);
    setExpandedFileGroups((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    if (!isExpanded) fileCatalog.loadGroup(id);
  };
  const refreshFileScope = () => {
    fileCatalog.reload();
    setExpandedFileGroups(
      firstFileGroupId ? new Set([firstFileGroupId]) : new Set()
    );
  };
  const maxFileSelect = capabilities?.sources.aidp.max_file_select ?? 20;
  const maxFileKbSelect = capabilities?.sources.aidp.max_select ?? 10;

  const toggleFile = (file: FileScopeFile) => {
    if (disabled || saving) return;
    setSelectionTouched(true);
    setDraft((current) => {
      const existing = getAidpFileScope(current).files;
      const key = `${file.kdsId}:${file.fileUuid}`;
      const isSelected = existing.some(
        (item) => `${item.kds_id}:${item.file_uuid}` === key
      );
      let nextFiles;
      if (isSelected) {
        nextFiles = existing.filter(
          (item) => `${item.kds_id}:${item.file_uuid}` !== key
        );
      } else {
        if (existing.length >= maxFileSelect) {
          message.warning(
            t("chat.knowledgeScope.fileScopeMax", { count: maxFileSelect })
          );
          return current;
        }
        const nextKbIds = new Set([
          ...existing.map((item) => item.kds_id),
          file.kdsId,
        ]);
        if (nextKbIds.size > maxFileKbSelect) {
          message.warning(
            t("chat.knowledgeScope.fileScopeMaxKbs", {
              count: maxFileKbSelect,
            })
          );
          return current;
        }
        nextFiles = [
          ...existing,
          {
            kds_id: file.kdsId,
            file_uuid: file.fileUuid,
            file_name: file.fileName,
            kds_name: file.kdsName,
          },
        ];
      }
      const kdsIds = Array.from(new Set(nextFiles.map((item) => item.kds_id)));
      return {
        ...current,
        schema_version: 2,
        local: { mode: "disabled", knowledge_ids: [] },
        aidp: {
          mode: kdsIds.length > 0 ? "override" : "inherit",
          kds_ids: kdsIds,
          file_scope: { mode: "selected", files: nextFiles },
        },
      };
    });
  };

  const removeFileByKey = (key: string) => {
    const file = selectedFiles.find(
      (item) => `${item.kds_id}:${item.file_uuid}` === key
    );
    if (file) {
      toggleFile({
        kdsId: file.kds_id,
        fileUuid: file.file_uuid,
        fileName: file.file_name || file.file_uuid,
        fileType: undefined,
        kdsName: file.kds_name || file.kds_id,
      });
    }
  };

  const switchScopeMode = (mode: "kb" | "files") => {
    if (mode === scopeMode || disabled || saving) return;
    if (mode === "files" && configuredSource !== "aidp") return;
    setSearch("");
    setPage(1);
    setSelectionTouched(true);
    setScopeMode(mode);
    if (mode === "files") {
      setDraft((current) => {
        const existing = getAidpFileScope(current);
        return {
          ...current,
          schema_version: 2,
          local: { mode: "disabled", knowledge_ids: [] },
          aidp: {
            ...current.aidp,
            mode:
              current.aidp.mode === "disabled" ? "inherit" : current.aidp.mode,
            file_scope:
              existing.mode === "selected"
                ? existing
                : { mode: "selected", files: [] },
          },
        };
      });
      return;
    }
    setDraft((current) => {
      const files = getAidpFileScope(current).files;
      const derivedIds = Array.from(new Set(files.map((file) => file.kds_id)));
      const nextKdsIds =
        derivedIds.length > 0
          ? derivedIds
          : current.aidp.kds_ids.length > 0
            ? current.aidp.kds_ids
            : defaultSelectedIds;
      return {
        ...current,
        schema_version: 1,
        local: { mode: "disabled", knowledge_ids: [] },
        aidp: {
          mode: nextKdsIds.length > 0 ? "override" : "inherit",
          kds_ids: nextKdsIds,
          file_scope: EMPTY_AIDP_FILE_SCOPE,
        },
      };
    });
  };

  const modeSwitch = (
    <Segmented
      block
      value={scopeMode}
      disabled={saving}
      onChange={(nextMode) => switchScopeMode(nextMode as "kb" | "files")}
      options={[
        {
          label: t("chat.knowledgeScope.modeKnowledge"),
          value: "kb",
        },
        {
          label: t("chat.knowledgeScope.modeFiles"),
          value: "files",
          disabled: configuredSource !== "aidp",
        },
      ]}
    />
  );

  const filePageItems = (
    current: number,
    total: number
  ): Array<number | "gap"> => {
    if (total <= 7) {
      return Array.from({ length: total }, (_, index) => index + 1);
    }
    const pages = Array.from(
      new Set([1, total, current - 1, current, current + 1])
    )
      .filter((item) => item >= 1 && item <= total)
      .sort((left, right) => left - right);
    const items: Array<number | "gap"> = [];
    pages.forEach((item, index) => {
      if (index > 0 && item - pages[index - 1] > 1) items.push("gap");
      items.push(item);
    });
    return items;
  };

  const renderSelectedFilePill = (groupId: string) => {
    const count = selectedCountByGroup.get(groupId) ?? 0;
    if (count === 0) return null;
    return (
      <span className="shrink-0 rounded-full bg-[#eaf2fd] px-1.5 py-0.5 text-[11px] leading-4 text-[#2f6fd0]">
        {t("chat.knowledgeScope.fileGroupSelected", { count })}
      </span>
    );
  };

  const renderFileRow = (file: FileScopeFile) => {
    const key = `${file.kdsId}:${file.fileUuid}`;
    const selected = selectedFileKeys.has(key);
    return (
      <label
        key={key}
        className={`flex cursor-pointer items-center gap-2.5 rounded-lg px-3 py-2 hover:bg-accent ${
          selected ? "bg-[#f5f9ff]" : ""
        }`}
      >
        <Checkbox
          checked={selected}
          disabled={disabled || saving}
          onChange={() => toggleFile(file)}
        />
        <span className="flex size-7 shrink-0 items-center justify-center rounded-[7px] bg-[#eaf2fd]">
          <FileText className="size-3.5 text-[#2f6fd0]" />
        </span>
        <span className="min-w-0 flex-1 truncate text-sm">{file.fileName}</span>
        {file.fileType ? (
          <span className="shrink-0 rounded border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
            {file.fileType.toUpperCase()}
          </span>
        ) : null}
      </label>
    );
  };

  const renderBrowseFileGroup = (group: FileScopeKnowledgeBase) => {
    const state: FileScopeGroupState = fileCatalog.groupStates[group.id] ?? {
      files: [],
      page: 1,
      total: 0,
      hasMore: false,
      loaded: false,
      loading: false,
      error: false,
    };
    const expanded = expandedFileGroups.has(group.id);
    const totalPages = Math.max(
      1,
      Math.ceil(state.total / FILE_SCOPE_BROWSE_PAGE_SIZE)
    );
    return (
      <section key={group.id} className="border-b border-border last:border-0">
        <button
          type="button"
          className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left hover:bg-accent"
          onClick={() => toggleFileGroup(group.id)}
          aria-expanded={expanded}
        >
          {expanded ? (
            <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
          )}
          <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
            {group.name}
          </span>
          {state.loaded ? (
            <span className="shrink-0 text-xs text-muted-foreground">
              {t("chat.knowledgeScope.fileGroupCount", { count: state.total })}
            </span>
          ) : null}
          {renderSelectedFilePill(group.id)}
        </button>
        {expanded ? (
          <div className="pb-1">
            {state.error ? (
              <div className="flex items-center justify-between gap-2 px-3 py-2 text-xs text-muted-foreground">
                <span>{t("chat.knowledgeScope.fileListLoadFailed")}</span>
                <Button
                  type="link"
                  size="small"
                  className="h-auto p-0 text-xs"
                  onClick={() => fileCatalog.loadGroup(group.id, state.page)}
                >
                  {t("chat.knowledgeScope.fileGroupRetry")}
                </Button>
              </div>
            ) : !state.loaded ? (
              <div className="flex justify-center py-5">
                <Spin size="small" />
              </div>
            ) : state.files.length === 0 ? (
              <div className="px-3 py-2 text-xs text-muted-foreground">
                {t("chat.knowledgeScope.fileEmpty")}
              </div>
            ) : (
              <Spin spinning={state.loading} size="small">
                {state.files.map(renderFileRow)}
                {totalPages > 1 ? (
                  <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs text-muted-foreground">
                    <span>
                      {t("chat.knowledgeScope.filePageLabel", {
                        page: state.page,
                        total: totalPages,
                      })}
                    </span>
                    <div className="flex items-center gap-1">
                      <Button
                        type="text"
                        size="small"
                        className="h-6 min-w-6 px-1"
                        disabled={state.page <= 1}
                        aria-label={t("chat.knowledgeScope.filePrevPage")}
                        onClick={() =>
                          fileCatalog.loadGroup(group.id, state.page - 1)
                        }
                      >
                        <ChevronLeft className="size-3.5" />
                      </Button>
                      {filePageItems(state.page, totalPages).map(
                        (item, index) =>
                          item === "gap" ? (
                            <span key={`gap-${index}`} className="px-1">
                              …
                            </span>
                          ) : (
                            <Button
                              key={item}
                              type={item === state.page ? "primary" : "text"}
                              size="small"
                              className="h-6 min-w-6 px-1.5"
                              onClick={() =>
                                fileCatalog.loadGroup(group.id, item)
                              }
                            >
                              {item}
                            </Button>
                          )
                      )}
                      <Button
                        type="text"
                        size="small"
                        className="h-6 min-w-6 px-1"
                        disabled={state.page >= totalPages}
                        aria-label={t("chat.knowledgeScope.fileNextPage")}
                        onClick={() =>
                          fileCatalog.loadGroup(group.id, state.page + 1)
                        }
                      >
                        <ChevronRight className="size-3.5" />
                      </Button>
                    </div>
                  </div>
                ) : null}
              </Spin>
            )}
          </div>
        ) : null}
      </section>
    );
  };

  const renderSearchFileGroup = (group: FileScopeKnowledgeBase) => {
    const result = fileCatalog.searchResults[group.id];
    if (!result || result.files.length === 0) return null;
    return (
      <section key={group.id} className="border-b border-border last:border-0">
        <div className="flex items-center gap-2 px-3 py-2.5">
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
            {group.name}
          </span>
          <span className="shrink-0 text-xs text-muted-foreground">
            {result.hasMore
              ? t("chat.knowledgeScope.fileSearchMatchesMore", {
                  count: result.files.length,
                })
              : t("chat.knowledgeScope.fileSearchMatches", {
                  count: result.files.length,
                })}
          </span>
          {renderSelectedFilePill(group.id)}
        </div>
        <div className="pb-1">{result.files.map(renderFileRow)}</div>
      </section>
    );
  };

  const renderFileScope = () => {
    if (fileScopeKnowledgeBases.length === 0) {
      return <Empty description={t("chat.knowledgeScope.fileModeNoKb")} />;
    }
    if (fileCatalog.searchActive) {
      const matchedGroups = fileScopeKnowledgeBases.filter(
        (group) => (fileCatalog.searchResults[group.id]?.files.length ?? 0) > 0
      );
      if (matchedGroups.length > 0) {
        return (
          <div className="divide-y divide-border">
            {matchedGroups.map(renderSearchFileGroup)}
          </div>
        );
      }
      if (fileCatalog.searchSettled && fileCatalog.searchHasSuccess) {
        return <Empty description={t("chat.knowledgeScope.fileSearchEmpty")} />;
      }
      return <div className="min-h-[120px]" />;
    }
    return (
      <div className="divide-y divide-border">
        {fileScopeKnowledgeBases.map(renderBrowseFileGroup)}
      </div>
    );
  };

  const getKnowledgeBaseId = (
    source: "local" | "aidp",
    knowledgeBase: KnowledgeBase
  ) =>
    source === "local"
      ? String(knowledgeBase.knowledge_id)
      : String(knowledgeBase.id);

  const getEmbeddingIdentity = (knowledgeBase: KnowledgeBase) =>
    String(
      knowledgeBase.embeddingModelId ?? knowledgeBase.embeddingModel ?? ""
    );

  const updateSelectedValues = (source: "local" | "aidp", values: string[]) => {
    setSelectionTouched(true);
    setRestoreDefaultClicked(false);
    const nextFileScope =
      source === "local"
        ? EMPTY_AIDP_FILE_SCOPE
        : fileScopeForSelection(draft, values);
    const previousCount = draft.aidp.file_scope?.files.length ?? 0;
    const nextCount = nextFileScope.files.length;
    if (previousCount > nextCount) {
      message.warning(
        t("chat.knowledgeScope.fileScopeRemoved", {
          count: previousCount - nextCount,
        })
      );
    }
    setDraft((current) =>
      withAidpFileScope(
        source === "local"
          ? {
              ...current,
              local: { mode: "override", knowledge_ids: values },
              aidp: { mode: "disabled", kds_ids: [] },
            }
          : {
              ...current,
              local: { mode: "disabled", knowledge_ids: [] },
              aidp: { mode: "override", kds_ids: values },
            },
        nextFileScope
      )
    );
  };

  const sameSelection = (left: string[], right: string[]) => {
    const rightIds = new Set(right);
    return (
      left.length === right.length &&
      new Set(left).size === rightIds.size &&
      left.every((id) => rightIds.has(id))
    );
  };

  const buildScopeForSelection = (
    source: "local" | "aidp",
    selectedIds: string[]
  ): ConversationKnowledgeScope => {
    if (selectedIds.length === 0) {
      return withAidpFileScope(
        {
          schema_version: 1,
          local: { mode: "disabled", knowledge_ids: [] },
          aidp: { mode: "disabled", kds_ids: [] },
        },
        EMPTY_AIDP_FILE_SCOPE
      );
    }
    if (sameSelection(selectedIds, defaultSelectedIds)) {
      return source === "local"
        ? withAidpFileScope(
            {
              schema_version: 1,
              local: { mode: "inherit", knowledge_ids: [] },
              aidp: { mode: "disabled", kds_ids: [] },
            },
            EMPTY_AIDP_FILE_SCOPE
          )
        : withAidpFileScope(
            {
              schema_version: 1,
              local: { mode: "disabled", knowledge_ids: [] },
              aidp: { mode: "inherit", kds_ids: [] },
            },
            fileScopeForSelection(draft, null)
          );
    }
    return source === "local"
      ? withAidpFileScope(
          {
            schema_version: 1,
            local: { mode: "override", knowledge_ids: selectedIds },
            aidp: { mode: "disabled", kds_ids: [] },
          },
          EMPTY_AIDP_FILE_SCOPE
        )
      : withAidpFileScope(
          {
            schema_version: 1,
            local: { mode: "disabled", knowledge_ids: [] },
            aidp: { mode: "override", kds_ids: selectedIds },
          },
          fileScopeForSelection(draft, selectedIds)
        );
  };

  const buildInheritScope = (
    source: "local" | "aidp"
  ): ConversationKnowledgeScope =>
    source === "local"
      ? withAidpFileScope(
          {
            schema_version: 1,
            local: { mode: "inherit", knowledge_ids: [] },
            aidp: { mode: "disabled", kds_ids: [] },
          },
          EMPTY_AIDP_FILE_SCOPE
        )
      : withAidpFileScope(
          {
            schema_version: 1,
            local: { mode: "disabled", knowledge_ids: [] },
            aidp: { mode: "inherit", kds_ids: [] },
          },
          fileScopeForSelection(draft, null)
        );

  const toggleKnowledgeBase = (source: "local" | "aidp", id: string) => {
    const currentValues =
      source === "local" ? draft.local.knowledge_ids : draft.aidp.kds_ids;
    if (currentValues.includes(id)) {
      updateSelectedValues(
        source,
        currentValues.filter((value) => value !== id)
      );
      return;
    }
    const maxSelect =
      capabilities?.sources[source].max_select ??
      (source === "local" ? 50 : 10);
    if (maxSelect > 0 && currentValues.length >= maxSelect) {
      message.warning(t("chat.knowledgeScope.maxSelect", { count: maxSelect }));
      return;
    }
    updateSelectedValues(source, [...currentValues, id]);
  };

  const validateLocalEmbeddingModels = (): boolean => {
    if (draft.local.mode !== "override") return true;
    const selected = new Set(draft.local.knowledge_ids);
    const models = new Set(
      localKnowledgeBases
        .filter(
          (kb) =>
            kb.knowledge_id !== undefined &&
            selected.has(String(kb.knowledge_id))
        )
        .map((kb) => String(kb.embeddingModelId ?? kb.embeddingModel ?? ""))
        .filter(Boolean)
    );
    if (models.size > 1) {
      message.error(t("chat.knowledgeScope.embeddingMismatch"));
      return false;
    }
    return true;
  };

  const handleConfirm = async () => {
    if (!configuredSource || loading || saving) return;
    const aidpNamesById = new Map(
      aidpOptions.map((option) => [String(option.value), String(option.label)])
    );
    if (scopeMode === "files") {
      if (configuredSource !== "aidp") return;
      const files = getAidpFileScope(draft).files;
      if (files.length === 0) {
        message.warning(t("chat.knowledgeScope.fileModeNeedsFile"));
        return;
      }
      const kdsIds = Array.from(new Set(files.map((file) => file.kds_id)));
      const nextScope: ConversationKnowledgeScope = {
        schema_version: 2,
        local: { mode: "disabled", knowledge_ids: [] },
        aidp: {
          mode: "override",
          kds_ids: kdsIds,
          file_scope: { mode: "selected", files },
        },
      };
      const preview: KnowledgeScopeEffectivePreview = {
        local: { disabled: true, knowledge_ids: [], display_names: [] },
        aidp: {
          disabled: false,
          kds_ids: kdsIds,
          display_names: kdsIds.map((id) => aidpNamesById.get(id) ?? id),
          file_scope: { mode: "selected", files },
        },
      };
      setSaving(true);
      try {
        await onConfirm(nextScope, preview);
      } catch {
        message.error(
          t("chat.knowledgeScope.saveFailed", "知识库配置保存失败，请重试")
        );
      } finally {
        setSaving(false);
      }
      return;
    }
    if (listError) return;
    const selectedIds =
      configuredSource === "local"
        ? draft.local.knowledge_ids
        : draft.aidp.kds_ids;
    let nextScope = buildScopeForSelection(configuredSource, selectedIds);
    if (
      !initialSelectionWasFiltered &&
      !selectionTouched &&
      sameSelection(selectedIds, initialSelectedIds)
    ) {
      nextScope = normalizeScopeForSource(value, configuredSource);
    }
    if (restoreDefaultClicked) {
      nextScope = buildInheritScope(configuredSource);
    }
    nextScope = withAidpFileScope(nextScope, EMPTY_AIDP_FILE_SCOPE);
    if (!validateLocalEmbeddingModels()) return;
    const localNamesById = new Map(
      localOptions.map((option) => [String(option.value), String(option.label)])
    );
    const preview: KnowledgeScopeEffectivePreview = {
      local: {
        disabled: nextScope.local.mode === "disabled",
        knowledge_ids:
          nextScope.local.mode === "override"
            ? nextScope.local.knowledge_ids
            : [],
        display_names:
          nextScope.local.mode === "override"
            ? nextScope.local.knowledge_ids.map(
                (id) => localNamesById.get(id) ?? id
              )
            : [],
      },
      aidp: {
        disabled: nextScope.aidp.mode === "disabled",
        kds_ids:
          nextScope.aidp.mode === "override" ? nextScope.aidp.kds_ids : [],
        display_names:
          nextScope.aidp.mode === "override"
            ? nextScope.aidp.kds_ids.map((id) => aidpNamesById.get(id) ?? id)
            : [],
        file_scope: EMPTY_AIDP_FILE_SCOPE,
      },
    };
    setSaving(true);
    try {
      await onConfirm(nextScope, preview);
    } catch {
      message.error(
        t("chat.knowledgeScope.saveFailed", "知识库配置保存失败，请重试")
      );
    } finally {
      setSaving(false);
    }
  };

  const filterKnowledgeBases = (source: "local" | "aidp") =>
    (source === "local" ? localKnowledgeBases : aidpKnowledgeBases).filter(
      (kb) =>
        (source !== "local" ||
          !tags.visibleIds ||
          tags.visibleIds.has(String(kb.id))) &&
        [kb.name, kb.display_name, kb.description].some((value) =>
          value?.toLowerCase().includes(search.trim().toLowerCase())
        )
    );

  const getSourceSelection = (source: "local" | "aidp") => {
    const values =
      source === "local" ? draft.local.knowledge_ids : draft.aidp.kds_ids;
    const allKnowledgeBases =
      source === "local" ? localKnowledgeBases : aidpKnowledgeBases;
    const filteredKnowledgeBases = filterKnowledgeBases(source);
    const selectedSet = new Set(values);
    const selectedKnowledgeBases = allKnowledgeBases.filter((knowledgeBase) =>
      selectedSet.has(getKnowledgeBaseId(source, knowledgeBase))
    );
    const selectedLocalModel =
      source === "local"
        ? selectedKnowledgeBases[0]
          ? getEmbeddingIdentity(selectedKnowledgeBases[0])
          : ""
        : "";
    const isCompatible = (knowledgeBase: KnowledgeBase) =>
      source !== "local" ||
      !selectedLocalModel ||
      !getEmbeddingIdentity(knowledgeBase) ||
      getEmbeddingIdentity(knowledgeBase) === selectedLocalModel;
    const knowledgeBases = filteredKnowledgeBases;
    const selectableKnowledgeBases = (
      presentation === "drawer"
        ? resourcePage(knowledgeBases, page, pageSize)
        : knowledgeBases
    ).filter(isCompatible);
    const selectableIds = selectableKnowledgeBases.map((knowledgeBase) =>
      getKnowledgeBaseId(source, knowledgeBase)
    );
    const allSelected =
      selectableIds.length > 0 &&
      selectableIds.every((id) => selectedSet.has(id));

    const handleSelectAll = () => {
      if (allSelected) {
        const visible = new Set(selectableIds);
        updateSelectedValues(
          source,
          values.filter((id) => !visible.has(id))
        );
        return;
      }
      let candidates = selectableKnowledgeBases;
      if (source === "local" && !selectedLocalModel && candidates.length > 0) {
        const firstModel = getEmbeddingIdentity(candidates[0]);
        if (firstModel) {
          candidates = candidates.filter(
            (knowledgeBase) =>
              getEmbeddingIdentity(knowledgeBase) === firstModel
          );
        }
      }
      const maxSelect =
        capabilities?.sources[source].max_select ??
        (source === "local" ? 50 : 10);
      const mergedIds = Array.from(
        new Set([
          ...values,
          ...candidates.map((knowledgeBase) =>
            getKnowledgeBaseId(source, knowledgeBase)
          ),
        ])
      );
      const nextValues =
        maxSelect > 0 ? mergedIds.slice(0, maxSelect) : mergedIds;
      if (nextValues.length < mergedIds.length) {
        message.warning(
          t("chat.knowledgeScope.maxSelect", { count: maxSelect })
        );
      }
      updateSelectedValues(source, nextValues);
    };

    return {
      values,
      selectedSet,
      selectedKnowledgeBases,
      selectedLocalModel,
      knowledgeBases,
      isCompatible,
      allSelected,
      selectableIds,
      handleSelectAll,
    };
  };
  const renderSource = (
    source: "local" | "aidp",
    section: "all" | "controls" | "list" = "all"
  ) => {
    const {
      values,
      selectedSet,
      selectedKnowledgeBases,
      selectedLocalModel,
      knowledgeBases,
      isCompatible,
      allSelected,
      selectableIds,
      handleSelectAll,
    } = getSourceSelection(source);
    if (presentation === "drawer") {
      return (
        <KnowledgeSelectionList
          knowledgeBases={resourcePage(knowledgeBases, page, pageSize).map(
            (kb) => ({
              ...kb,
              id: getKnowledgeBaseId(source, kb),
            })
          )}
          isAidpSearch={source === "aidp"}
          groupNamesFor={(kb) =>
            (kb.group_ids ?? [])
              .map((id) => groupNameById.get(id))
              .filter((name): name is string => Boolean(name))
          }
          selection={{
            ids: selectedSet,
            toggle: (id) => toggleKnowledgeBase(source, id),
            canSelect: (kb) => selectedSet.has(kb.id) || isCompatible(kb),
            disabledReason: (kb) =>
              !isCompatible(kb)
                ? t("chat.knowledgeScope.embeddingMismatch")
                : undefined,
          }}
          slots={{
            renderTags: (item) => (
              <>
                {(item.tags ?? []).map((tag) => (
                  <span
                    key={tag}
                    className="rounded bg-muted px-1.5 text-xs text-muted-foreground"
                  >
                    {tag}
                  </span>
                ))}
              </>
            ),
          }}
        />
      );
    }
    return (
      <div
        className={
          section === "all"
            ? "overflow-hidden rounded-lg border border-border bg-background"
            : section === "controls"
              ? "overflow-hidden rounded-lg"
              : "min-h-full"
        }
      >
        {section !== "list" && (
          <div className="rounded bg-blue-50 px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <SelectedResourceTags
                items={selectedKnowledgeBases.map((kb) => ({
                  id: getKnowledgeBaseId(source, kb),
                  name: kb.display_name || kb.name,
                }))}
                onRemove={(id) => toggleKnowledgeBase(source, id)}
              />
              <ResourceSelectionActions
                pageOnly={false}
                allSelected={allSelected}
                hasSelection={values.length > 0}
                disabled={loading || saving || listError}
                empty={selectableIds.length === 0}
                onToggleAll={handleSelectAll}
                onClear={() => updateSelectedValues(source, [])}
              />
            </div>
          </div>
        )}
        {section !== "controls" &&
          (knowledgeBases.length === 0 ? (
            <div
              className={`${section === "list" ? "min-h-full" : RESOURCE_SELECTION_AREA_CLASS} flex items-center justify-center`}
            >
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("chat.knowledgeScope.empty")}
              />
            </div>
          ) : (
            <ResourceSelectionGrid
              layout="grid"
              aria-label={t("chat.knowledgeScope.title")}
              fillAvailable={section === "list"}
              columns={3}
              className="p-1"
            >
              {resourcePage(knowledgeBases, page, pageSize).map(
                (knowledgeBase) => {
                  const id = getKnowledgeBaseId(source, knowledgeBase);
                  const isSelected = selectedSet.has(id);
                  const modelIdentity = getEmbeddingIdentity(knowledgeBase);
                  const disabledByModel =
                    source === "local" &&
                    !isSelected &&
                    Boolean(selectedLocalModel) &&
                    Boolean(modelIdentity) &&
                    modelIdentity !== selectedLocalModel;
                  const name = knowledgeBase.display_name || knowledgeBase.name;
                  const groupNames = (knowledgeBase.group_ids ?? [])
                    .map((groupId) => groupNameById.get(groupId))
                    .filter((groupName): groupName is string =>
                      Boolean(groupName)
                    );
                  return (
                    <ResourceCard
                      resourceType="knowledge"
                      key={id}
                      title={name}
                      tags={knowledgeBase.tags || []}
                      description={knowledgeBase.description || undefined}
                      subtitle={
                        source === "local"
                          ? `${knowledgeBase.documentCount ?? 0} ${t("knowledgeBase.document", "篇文档")}`
                          : undefined
                      }
                      selected={isSelected}
                      disabled={disabledByModel}
                      onClick={() => toggleKnowledgeBase(source, id)}
                      actions={
                        <Button
                          size="small"
                          aria-label={t("ui.localization.edit")}
                          onClick={() => router.push("/knowledges")}
                        >
                          {t("ui.localization.edit")}
                        </Button>
                      }
                      badges={[
                        source === "local"
                          ? t("ui.localization.local")
                          : "AIDP",
                        knowledgeBase.permission,
                        ...(source === "local" &&
                        knowledgeBase.embeddingModel &&
                        knowledgeBase.embeddingModel !== "unknown"
                          ? [
                              t("knowledgeBase.tag.model", {
                                model: knowledgeBase.embeddingModel,
                              }),
                            ]
                          : []),
                        ...(knowledgeBase.ingroup_permission === "PRIVATE"
                          ? [t("knowledgeBase.ingroup.permission.PRIVATE")]
                          : groupNames),
                        ...(knowledgeBase.is_multimodal ? ["multimodal"] : []),
                      ]}
                      disabledReason={
                        disabledByModel
                          ? t("chat.knowledgeScope.embeddingMismatch")
                          : undefined
                      }
                      footer={
                        disabledByModel
                          ? t("chat.knowledgeScope.embeddingMismatch")
                          : isSelected
                            ? t("common.selected", "已选择")
                            : t("common.select", "选择")
                      }
                    />
                  );
                }
              )}
            </ResourceSelectionGrid>
          ))}
        {section === "all" && (
          <ResourcePagination
            current={page}
            total={knowledgeBases.length}
            onChange={setPage}
            disabled={loading || saving}
          />
        )}
      </div>
    );
  };

  const source = configuredSource;
  const drawerKnowledge =
    source === "local" ? localKnowledgeBases : aidpKnowledgeBases;
  const selectedScopeIds =
    source === "local" ? draft.local.knowledge_ids : draft.aidp.kds_ids;
  const knowledgeWarnings = (
    <>
      {value &&
        ((value.local.mode === "override" && configuredSource === "aidp") ||
          (value.aidp.mode === "override" && configuredSource === "local")) && (
          <Alert
            className="mb-3"
            type="warning"
            showIcon
            title={t("chat.knowledgeScope.incompatible")}
          />
        )}
      {capabilities?.legacy_prompt_warning?.detected && (
        <Alert
          className="mb-3"
          type="warning"
          showIcon
          title={t("chat.knowledgeScope.legacyPromptWarning")}
          description={t("chat.knowledgeScope.affectedAgents", {
            ids: capabilities.legacy_prompt_warning.affected_agent_ids.join(
              ", "
            ),
          })}
          action={
            <Button
              size="small"
              onClick={() => {
                onCancel();
                router.push("/agents");
              }}
            >
              {t("chat.knowledgeScope.goToAgentConfig")}
            </Button>
          }
        />
      )}
    </>
  );
  const drawerFooter = (
    <div className="flex items-center gap-3">
      <RestoreDefaultsButton
        disabled={loading || listError || saving || !configuredSource}
        onClick={() => {
          if (!configuredSource) return;
          setScopeMode("kb");
          setDraft(
            configuredSource === "local"
              ? {
                  schema_version: 1,
                  local: {
                    mode: "override",
                    knowledge_ids: defaultSelectedIds,
                  },
                  aidp: { mode: "disabled", kds_ids: [] },
                }
              : {
                  schema_version: 1,
                  local: { mode: "disabled", knowledge_ids: [] },
                  aidp: {
                    mode: "override",
                    kds_ids: defaultSelectedIds,
                    file_scope: EMPTY_AIDP_FILE_SCOPE,
                  },
                }
          );
          setSelectionTouched(true);
          setRestoreDefaultClicked(true);
        }}
      >
        {t("chat.knowledgeScope.restoreDefault")}
      </RestoreDefaultsButton>
    </div>
  );
  const drawerSelection = source ? getSourceSelection(source) : null;
  const fileMode = scopeMode === "files";
  const selectedFileOptions = selectedFiles.map((file) => {
    const name = file.file_name || file.file_uuid;
    const kbName =
      file.kds_name ||
      aidpOptions.find((option) => String(option.value) === String(file.kds_id))
        ?.label ||
      file.kds_id;
    return {
      id: `${file.kds_id}:${file.file_uuid}`,
      label: duplicatedSelectedNames.has(name) ? `${name} · ${kbName}` : name,
    };
  });
  const scopeDrawer = (
    <WorkbenchResourceDrawer
      open={open}
      title={t("chat.knowledgeScope.scopeTitle")}
      onCancel={onCancel}
      onConfirm={() => {
        if (!disabled) void handleConfirm();
      }}
      saving={saving}
      disabled={disabled}
      confirmDisabled={
        fileMode
          ? selectedFiles.length === 0
          : loading ||
            listError ||
            !source ||
            (!!tags.predicates.length && tags.loading)
      }
      picker={
        fileMode
          ? {
              keyword: search,
              searchPlaceholder: t("chat.knowledgeScope.fileSearchPlaceholder"),
              onSearch: setSearch,
              listTitle: t("chat.knowledgeScope.fileList"),
              selected: selectedFileOptions,
              onRemoveSelected: removeFileByKey,
              headerContent: modeSwitch,
              controlsContent: (
                <div className="text-xs text-muted-foreground">
                  {t("chat.knowledgeScope.fileSelectedCount", {
                    count: selectedFiles.length,
                    max: maxFileSelect,
                  })}
                </div>
              ),
              showPagination: false,
              onRefresh: refreshFileScope,
              refreshDisabled: saving,
            }
          : {
              keyword: search,
              searchPlaceholder: t(
                "resourcePicker.search.knowledge",
                "搜索知识库名称及描述"
              ),
              onSearch: setSearch,
              headerContent: modeSwitch,
              tagFilter:
                source === "local" ? (
                  <ResourceTagFilter
                    filter={tags}
                    onChange={() => setPage(1)}
                  />
                ) : undefined,
              listTitle: t("resourcePicker.list.knowledge", "知识库列表"),
              selected: drawerKnowledge
                .filter((kb) =>
                  selectedScopeIds.includes(
                    getKnowledgeBaseId(source ?? "local", kb)
                  )
                )
                .map((kb) => ({
                  id: getKnowledgeBaseId(source ?? "local", kb),
                  label: kb.display_name || kb.name,
                })),
              onRemoveSelected: (id) => {
                if (source) toggleKnowledgeBase(source, id);
              },
              total: source ? filterKnowledgeBases(source).length : 0,
              page,
              pageSize,
              onPageSizeChange: (size) => {
                setPageSize(size);
                setPage(1);
              },
              onPageChange: setPage,
              onSelectAll: drawerSelection
                ? drawerSelection.handleSelectAll
                : undefined,
              allSelected: drawerSelection?.allSelected,
              partiallySelected: Boolean(
                drawerSelection &&
                !drawerSelection.allSelected &&
                drawerSelection.selectableIds.some((id) =>
                  drawerSelection.selectedSet.has(id)
                )
              ),
              selectAllDisabled:
                loading ||
                saving ||
                listError ||
                !drawerSelection?.selectableIds.length,
              onRefresh: () => {
                if (loading || saving) return;
                setListError(false);
                tags.retry?.();
                setRefreshRevision((value) => value + 1);
              },
              refreshDisabled: loading || saving || !source,
              controlsContent:
                listError ||
                capabilities?.legacy_prompt_warning?.detected ||
                (value &&
                  ((value.local.mode === "override" && source === "aidp") ||
                    (value.aidp.mode === "override" && source === "local"))) ? (
                  <>
                    {knowledgeWarnings}
                    {listError && (
                      <Alert
                        type="error"
                        title={t("chat.knowledgeScope.listLoadFailed")}
                      />
                    )}
                  </>
                ) : undefined,
            }
      }
      listContent={
        fileMode ? (
          renderFileScope()
        ) : (
          <Spin spinning={loading || !isDeploymentReady}>
            {source ? (
              renderSource(source, "list")
            ) : (
              <Empty description={t("chat.knowledgeScope.noTool")} />
            )}
          </Spin>
        )
      }
    >
      {null}
    </WorkbenchResourceDrawer>
  );
  return (
    <>
      {presentation === "drawer" ? (
        scopeDrawer
      ) : (
        <ResourcePickerPresentation
          presentation={presentation}
          disabled={disabled}
          title={t("chat.knowledgeScope.scopeTitle")}
          open={open}
          onCancel={onCancel}
          onOk={() => {
            if (!disabled) void handleConfirm();
          }}
          okText={t("chat.knowledgeScope.confirm")}
          cancelText={t("chat.knowledgeScope.cancel")}
          confirmLoading={saving}
          okButtonProps={{
            disabled: fileMode
              ? selectedFiles.length === 0
              : loading ||
                listError ||
                !configuredSource ||
                (!!tags.predicates.length && tags.loading),
          }}
          width={920}
          centered
          footer={(_, { OkBtn, CancelBtn }) => (
            <div className="flex items-center justify-between">
              {drawerFooter}
              <div className="flex gap-2">
                <CancelBtn />
                <OkBtn />
              </div>
            </div>
          )}
        >
          {knowledgeWarnings}
          <Spin spinning={fileMode ? false : loading || !isDeploymentReady}>
            <div className="space-y-3 py-2">
              {modeSwitch}
              {fileMode ? (
                configuredSource === "aidp" ? (
                  <>
                    <Input.Search
                      aria-label={t(
                        "chat.knowledgeScope.fileSearchPlaceholder"
                      )}
                      value={search}
                      onChange={(event) => {
                        setSearch(event.target.value);
                      }}
                      placeholder={t(
                        "chat.knowledgeScope.fileSearchPlaceholder"
                      )}
                      allowClear
                    />
                    <div className="text-xs text-muted-foreground">
                      <span>
                        {t("chat.knowledgeScope.fileSelectedCount", {
                          count: selectedFiles.length,
                          max: maxFileSelect,
                        })}
                      </span>
                    </div>
                    {renderFileScope()}
                  </>
                ) : (
                  <Empty description={t("chat.knowledgeScope.noTool")} />
                )
              ) : configuredSource ? (
                <>
                  <ResourceTagFilter
                    filter={tags}
                    onChange={() => setPage(1)}
                    showFilter={false}
                    search={
                      <Input.Search
                        aria-label={t(
                          "workbench.controls.searchKnowledgeLabel"
                        )}
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                        placeholder={t("workbench.controls.searchKnowledge")}
                        allowClear
                      />
                    }
                  />
                  {renderSource(configuredSource, "all")}
                </>
              ) : (
                <Empty description={t("chat.knowledgeScope.noTool")} />
              )}
            </div>
          </Spin>
        </ResourcePickerPresentation>
      )}
    </>
  );
};
