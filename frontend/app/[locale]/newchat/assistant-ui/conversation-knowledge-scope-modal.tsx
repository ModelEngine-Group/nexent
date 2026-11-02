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
import { Alert, Button, Empty, Input, Spin, message } from "antd";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { useGroupList } from "@/hooks/group/useGroupList";
import type { KnowledgeBase } from "@/types/knowledgeBase";
import type {
  ConversationKnowledgeScope,
  KnowledgeCapabilities,
  KnowledgeScopeEffectivePreview,
} from "@/types/knowledgeScope";
import { DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE } from "@/types/knowledgeScope";
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
      schema_version: 1,
      local: (value || DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE).local,
      aidp: (value || DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE).aidp,
    })
  ) as ConversationKnowledgeScope;

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
    return {
      schema_version: 1,
      local: { mode: "inherit", knowledge_ids: [] },
      aidp: { mode: "disabled", kds_ids: [] },
    };
  }
  if (source === "aidp" && scope.aidp.mode === "inherit") {
    return {
      ...scope,
      schema_version: 1,
      local: { mode: "disabled", knowledge_ids: [] },
      aidp: { mode: "inherit", kds_ids: [] },
    };
  }
  if (source === "local" && scope.local.mode === "override") {
    return {
      ...scope,
      aidp: { mode: "disabled", kds_ids: [] },
    };
  }
  if (source === "aidp" && scope.aidp.mode === "override") {
    return {
      ...scope,
      local: { mode: "disabled", knowledge_ids: [] },
    };
  }
  return {
    schema_version: 1,
    local: { mode: "disabled", knowledge_ids: [] },
    aidp: { mode: "disabled", kds_ids: [] },
  };
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
    setDraft((current) =>
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
          }
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
      return {
        schema_version: 1,
        local: { mode: "disabled", knowledge_ids: [] },
        aidp: { mode: "disabled", kds_ids: [] },
      };
    }
    if (sameSelection(selectedIds, defaultSelectedIds)) {
      return source === "local"
        ? {
            schema_version: 1,
            local: { mode: "inherit", knowledge_ids: [] },
            aidp: { mode: "disabled", kds_ids: [] },
          }
        : {
            schema_version: 1,
            local: { mode: "disabled", knowledge_ids: [] },
            aidp: { mode: "inherit", kds_ids: [] },
          };
    }
    return source === "local"
      ? {
          schema_version: 1,
          local: { mode: "override", knowledge_ids: selectedIds },
          aidp: { mode: "disabled", kds_ids: [] },
        }
      : {
          schema_version: 1,
          local: { mode: "disabled", knowledge_ids: [] },
          aidp: { mode: "override", kds_ids: selectedIds },
        };
  };

  const buildInheritScope = (
    source: "local" | "aidp"
  ): ConversationKnowledgeScope =>
    source === "local"
      ? {
          schema_version: 1,
          local: { mode: "inherit", knowledge_ids: [] },
          aidp: { mode: "disabled", kds_ids: [] },
        }
      : {
          schema_version: 1,
          local: { mode: "disabled", knowledge_ids: [] },
          aidp: { mode: "inherit", kds_ids: [] },
        };

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
    if (!configuredSource || loading || saving || listError) return;
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
    if (!validateLocalEmbeddingModels()) return;
    const localNamesById = new Map(
      localOptions.map((option) => [String(option.value), String(option.label)])
    );
    const aidpNamesById = new Map(
      aidpOptions.map((option) => [String(option.value), String(option.label)])
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
  const scopeDrawer = (
    <WorkbenchResourceDrawer
      open={open}
      title={t("chat.knowledgeScope.title")}
      onCancel={onCancel}
      onConfirm={() => {
        if (!disabled) void handleConfirm();
      }}
      saving={saving}
      disabled={disabled}
      confirmDisabled={
        loading ||
        listError ||
        !source ||
        (!!tags.predicates.length && tags.loading)
      }
      picker={{
        keyword: search,
        searchPlaceholder: t(
          "resourcePicker.search.knowledge",
          "搜索知识库名称及描述"
        ),
        onSearch: setSearch,
        tagFilter:
          source === "local" ? (
            <ResourceTagFilter filter={tags} onChange={() => setPage(1)} />
          ) : undefined,
        listTitle: t("resourcePicker.list.knowledge", "知识库列表"),
        selected: drawerKnowledge
          .filter((kb) =>
            selectedScopeIds.includes(getKnowledgeBaseId(source ?? "local", kb))
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
      }}
      listContent={
        <Spin spinning={loading || !isDeploymentReady}>
          {source ? (
            renderSource(source, "list")
          ) : (
            <Empty description={t("chat.knowledgeScope.noTool")} />
          )}
        </Spin>
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
          title={t("chat.knowledgeScope.title")}
          open={open}
          onCancel={onCancel}
          onOk={() => {
            if (!disabled) void handleConfirm();
          }}
          okText={t("chat.knowledgeScope.confirm")}
          cancelText={t("chat.knowledgeScope.cancel")}
          confirmLoading={saving}
          okButtonProps={{
            disabled:
              loading ||
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
          <Spin spinning={loading || !isDeploymentReady}>
            {configuredSource ? (
              <div className="space-y-3 py-2">
                <ResourceTagFilter
                  filter={tags}
                  onChange={() => setPage(1)}
                  showFilter={false}
                  search={
                    <Input.Search
                      aria-label={t("workbench.controls.searchKnowledgeLabel")}
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder={t("workbench.controls.searchKnowledge")}
                      allowClear
                    />
                  }
                />
                {renderSource(configuredSource, "all")}
              </div>
            ) : (
              <Empty description={t("chat.knowledgeScope.noTool")} />
            )}
          </Spin>
        </ResourcePickerPresentation>
      )}
    </>
  );
};
