"use client";

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

import { useEffect, useMemo, useState, type FC } from "react";
import { useTranslation } from "react-i18next";
import { useRouter } from "next/navigation";
import { Alert, Button, Empty, Input, Modal, Spin, message } from "antd";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { useGroupList } from "@/hooks/group/useGroupList";
import type { KnowledgeBase } from "@/types/knowledgeBase";
import type { ToolParam } from "@/types/agentConfig";
import type {
  ConversationKnowledgeScope,
  KnowledgeCapabilities,
  KnowledgeScopeEffectivePreview,
} from "@/types/knowledgeScope";
import { DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE } from "@/types/knowledgeScope";
import { ResourceCard } from "@/features/workbench";
import { KnowledgeRetrievalParamsForm } from "@/components/tool-config/KnowledgeRetrievalParamsForm";
import { useToolList } from "@/hooks/agent/useToolList";
import {
  AIDP_NON_PERSISTED_PARAM_NAMES,
  getSemanticToolName,
} from "@/lib/managedKnowledgeTools";
import { RestoreDefaultsButton } from "@/features/workbench/components/RestoreDefaultsButton";

interface ConversationKnowledgeScopeModalProps {
  open: boolean;
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
    JSON.stringify(value || DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE)
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
> = ({ open, value, capabilities, onCancel, onConfirm }) => {
  const { t } = useTranslation();
  const router = useRouter();
  const { enableAidpKnowledge, isDeploymentReady } = useDeployment();
  const { availableTools, isLoading: toolsLoading } = useToolList({
    enabled: open && isDeploymentReady,
  });
  const [paramsOpen, setParamsOpen] = useState(false);
  const [retrievalConfig, setRetrievalConfig] = useState<
    Record<string, unknown>
  >({});
  const [paramDraft, setParamDraft] = useState<Record<string, unknown>>({});
  const knowledgeTool = availableTools.find(
    (tool) =>
      getSemanticToolName(tool) ===
      (enableAidpKnowledge ? "aidp_search" : "knowledge_base_search")
  );
  const configurableParams: ToolParam[] = (
    knowledgeTool?.initParams || []
  ).filter(
    (param: ToolParam) =>
      !["index_names", "kds_list"].includes(param.name) &&
      !AIDP_NON_PERSISTED_PARAM_NAMES.has(param.name)
  );
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
  const [loading, setLoading] = useState(false);
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
  useEffect(() => {
    setPage(1);
  }, [open, search, enableAidpKnowledge]);

  useEffect(() => {
    if (!open || !configuredSource) return;
    setParamsOpen(false);
    const incompatible =
      configuredSource === "aidp"
        ? value?.local.mode === "override"
        : value?.aidp.mode === "override";
    setRetrievalConfig(
      incompatible ? {} : structuredClone(value?.retrieval_config || {})
    );
    const normalized = normalizeScopeForSource(value, configuredSource);
    setDraft(normalized);
    setInitialSelectionWasFiltered(false);
    setSelectionTouched(false);
    setRestoreDefaultClicked(false);
    setSearch("");
    setListError(false);
    let cancelled = false;
    setLoading(true);
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
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, value, configuredSource, capabilities, t]);

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
    if (Object.keys(retrievalConfig).length)
      nextScope.retrieval_config = structuredClone(retrievalConfig);
    else delete nextScope.retrieval_config;
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

  const renderSource = (source: "local" | "aidp") => {
    const values =
      source === "local" ? draft.local.knowledge_ids : draft.aidp.kds_ids;
    const allKnowledgeBases =
      source === "local" ? localKnowledgeBases : aidpKnowledgeBases;
    const filteredKnowledgeBases = allKnowledgeBases.filter((kb) =>
      [kb.name, kb.display_name, kb.description].some((value) =>
        value?.toLowerCase().includes(search.trim().toLowerCase())
      )
    );
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
    const selectableKnowledgeBases = knowledgeBases.filter(isCompatible);
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

    return (
      <div className="overflow-hidden rounded-lg border border-border bg-background">
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
              allSelected={allSelected}
              hasSelection={values.length > 0}
              disabled={loading || saving || listError}
              empty={selectableIds.length === 0}
              onToggleAll={handleSelectAll}
              onClear={() => updateSelectedValues(source, [])}
            />
          </div>
        </div>

        {knowledgeBases.length === 0 ? (
          <div
            className={`${RESOURCE_SELECTION_AREA_CLASS} flex items-center justify-center`}
          >
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("chat.knowledgeScope.empty")}
            />
          </div>
        ) : (
          <ResourceSelectionGrid className="p-1">
            {resourcePage(knowledgeBases, page).map((knowledgeBase) => {
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
                .filter((groupName): groupName is string => Boolean(groupName));
              return (
                <ResourceCard
                  resourceType="knowledge"
                  key={id}
                  title={name}
                  tags={knowledgeBase.tags || []}
                  description={knowledgeBase.description || undefined}
                  subtitle={`${knowledgeBase.documentCount ?? 0} ${t("knowledgeBase.document", "篇文档")}`}
                  selected={isSelected}
                  disabled={disabledByModel}
                  onClick={() => toggleKnowledgeBase(source, id)}
                  actions={
                    <Button
                      size="small"
                      aria-label="编辑"
                      onClick={() => router.push("/knowledges")}
                    >
                      编辑
                    </Button>
                  }
                  badges={[
                    source === "local" ? "本地" : "AIDP",
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
            })}
          </ResourceSelectionGrid>
        )}
        <ResourcePagination
          current={page}
          total={knowledgeBases.length}
          onChange={setPage}
          disabled={loading || saving}
        />
      </div>
    );
  };

  return (
    <Modal
      title={t("chat.knowledgeScope.title")}
      open={open}
      onCancel={onCancel}
      onOk={handleConfirm}
      okText={t("chat.knowledgeScope.confirm")}
      cancelText={t("chat.knowledgeScope.cancel")}
      confirmLoading={saving}
      okButtonProps={{ disabled: loading || listError || !configuredSource }}
      width={920}
      centered
      footer={(_, { OkBtn, CancelBtn }) => (
        <div className="flex items-center justify-between">
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
                setRetrievalConfig({});
              }}
            >
              {t("chat.knowledgeScope.restoreDefault")}
            </RestoreDefaultsButton>
            <Button
              disabled={
                loading ||
                saving ||
                toolsLoading ||
                !knowledgeTool ||
                !configuredSource
              }
              onClick={() => {
                setParamDraft(structuredClone(retrievalConfig));
                setParamsOpen(true);
              }}
            >
              配置
            </Button>
          </div>
          <div className="flex gap-2">
            <CancelBtn />
            <OkBtn />
          </div>
        </div>
      )}
    >
      {value &&
        ((value.local.mode === "override" && configuredSource === "aidp") ||
          (value.aidp.mode === "override" && configuredSource === "local")) && (
          <Alert
            className="mb-3"
            type="warning"
            showIcon
            message={t("chat.knowledgeScope.incompatible")}
          />
        )}
      {capabilities?.legacy_prompt_warning?.detected && (
        <Alert
          className="mb-3"
          type="warning"
          showIcon
          message={t("chat.knowledgeScope.legacyPromptWarning")}
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
      <Spin spinning={loading || !isDeploymentReady}>
        {configuredSource ? (
          <div className="space-y-3 py-2">
            <Input.Search
              aria-label="搜索知识库"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索名称或描述"
              allowClear
            />
            <Modal
              open={paramsOpen}
              title={t("agent.knowledge.configModal.title")}
              onCancel={() => setParamsOpen(false)}
              okText="确定"
              cancelText="取消"
              onOk={() => {
                setRetrievalConfig(structuredClone(paramDraft));
                setParamsOpen(false);
              }}
            >
              <KnowledgeRetrievalParamsForm
                params={configurableParams}
                values={Object.fromEntries(
                  configurableParams.map((param) => [
                    param.name,
                    paramDraft[param.name] ??
                      (configuredSource
                        ? capabilities?.sources[configuredSource]
                            .default_retrieval_config?.[param.name]
                        : undefined) ??
                      param.value ??
                      param.default,
                  ])
                )}
                onChange={(name, nextValue) =>
                  setParamDraft((current) => {
                    const next = { ...current };
                    if (nextValue === null || nextValue === undefined)
                      delete next[name];
                    else next[name] = nextValue;
                    return next;
                  })
                }
              />
            </Modal>
            {renderSource(configuredSource)}
          </div>
        ) : null}
      </Spin>
    </Modal>
  );
};
