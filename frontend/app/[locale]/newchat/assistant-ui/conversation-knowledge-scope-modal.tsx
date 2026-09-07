"use client";

import { useEffect, useMemo, useState, type FC } from "react";
import { useTranslation } from "react-i18next";
import { useRouter } from "next/navigation";
import { Alert, Button, Checkbox, Empty, Modal, Spin, message } from "antd";

import { Can } from "@/components/permission/Can";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { KB_LAYOUT, KB_TAG_VARIANTS } from "@/const/knowledgeBaseLayout";
import { useGroupList } from "@/hooks/group/useGroupList";
import type { KnowledgeBase } from "@/types/knowledgeBase";
import type {
  ConversationKnowledgeScope,
  KnowledgeCapabilities,
  KnowledgeScopeEffectivePreview,
} from "@/types/knowledgeScope";
import { DEFAULT_CONVERSATION_KNOWLEDGE_SCOPE } from "@/types/knowledgeScope";

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
  return copyScope(null);
};

export const ConversationKnowledgeScopeModal: FC<
  ConversationKnowledgeScopeModalProps
> = ({ open, value, capabilities, onCancel, onConfirm }) => {
  const { t } = useTranslation();
  const router = useRouter();
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
  const hasSourceConflict = Boolean(
    capabilities?.sources.local.enabled && capabilities.sources.aidp.enabled
  );
  const configuredSource: "local" | "aidp" | null = hasSourceConflict
    ? null
    : capabilities?.sources.local.enabled
      ? "local"
      : capabilities?.sources.aidp.enabled
        ? "aidp"
        : null;
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
  const [saving, setSaving] = useState(false);
  const [initialSelectedIds, setInitialSelectedIds] = useState<string[]>([]);
  const [initialSelectionWasFiltered, setInitialSelectionWasFiltered] =
    useState(false);
  const [defaultSelectedIds, setDefaultSelectedIds] = useState<string[]>([]);
  const [selectionTouched, setSelectionTouched] = useState(false);
  const [restoreDefaultClicked, setRestoreDefaultClicked] = useState(false);

  useEffect(() => {
    if (!open) return;
    const normalized = normalizeScopeForSource(value, configuredSource);
    setDraft(normalized);
    setInitialSelectionWasFiltered(false);
    setSelectionTouched(false);
    setRestoreDefaultClicked(false);
    let cancelled = false;
    setLoading(true);
    Promise.all([
      configuredSource === "local"
        ? knowledgeBaseService.getKnowledgeBasesInfo(false, false)
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
        if (!cancelled) message.error(t("chat.knowledgeScope.listLoadFailed"));
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
    const maxSelect = capabilities?.sources[source].max_select ?? 0;
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
    if (!configuredSource) return;
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
    } finally {
      setSaving(false);
    }
  };

  const renderSource = (source: "local" | "aidp") => {
    const values =
      source === "local" ? draft.local.knowledge_ids : draft.aidp.kds_ids;
    const knowledgeBases =
      source === "local" ? localKnowledgeBases : aidpKnowledgeBases;
    const selectedSet = new Set(values);
    const selectedKnowledgeBases = knowledgeBases.filter((knowledgeBase) =>
      selectedSet.has(getKnowledgeBaseId(source, knowledgeBase))
    );
    const selectedLocalModel =
      source === "local"
        ? selectedKnowledgeBases[0]
          ? getEmbeddingIdentity(selectedKnowledgeBases[0])
          : ""
        : "";
    const selectableKnowledgeBases = knowledgeBases.filter(
      (knowledgeBase) =>
        source !== "local" ||
        !selectedLocalModel ||
        !getEmbeddingIdentity(knowledgeBase) ||
        getEmbeddingIdentity(knowledgeBase) === selectedLocalModel
    );
    const selectableIds = selectableKnowledgeBases.map((knowledgeBase) =>
      getKnowledgeBaseId(source, knowledgeBase)
    );
    const allSelected =
      selectableIds.length > 0 &&
      selectableIds.every((id) => selectedSet.has(id));

    const handleSelectAll = () => {
      if (allSelected) {
        updateSelectedValues(source, []);
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
      const maxSelect = capabilities?.sources[source].max_select ?? 0;
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
        <div className="border-b border-blue-100 bg-blue-50 px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-blue-800">
                {source === "local"
                  ? t("chat.knowledgeScope.localTab")
                  : t("chat.knowledgeScope.aidpTab")}
              </div>
              <div className="mt-0.5 text-xs text-blue-700">
                {t("knowledgeBase.selected.prefix")} {values.length}{" "}
                {t("knowledgeBase.selected.suffix")}
              </div>
            </div>
            <div className="flex items-center gap-3">
              {knowledgeBases.length > 0 && (
                <Button
                  type="link"
                  size="small"
                  className="h-auto p-0 font-medium"
                  onClick={handleSelectAll}
                >
                  {allSelected
                    ? t("common.deselectAll")
                    : t("knowledgeBase.button.selectAll")}
                </Button>
              )}
              {values.length > 0 && (
                <Button
                  type="link"
                  size="small"
                  danger
                  className="h-auto p-0 font-medium"
                  onClick={() => updateSelectedValues(source, [])}
                >
                  {t("knowledgeBase.button.clearSelection")}
                </Button>
              )}
            </div>
          </div>
          {selectedKnowledgeBases.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {selectedKnowledgeBases.map((knowledgeBase) => {
                const id = getKnowledgeBaseId(source, knowledgeBase);
                const name = knowledgeBase.display_name || knowledgeBase.name;
                return (
                  <span
                    key={id}
                    className="inline-flex max-w-48 items-center rounded bg-blue-100 px-2 py-0.5 text-sm font-medium text-blue-800"
                  >
                    <span className="truncate" title={name}>
                      {name}
                    </span>
                    <button
                      type="button"
                      className="ml-1.5 shrink-0 text-blue-600 hover:text-blue-800"
                      onClick={() => toggleKnowledgeBase(source, id)}
                      aria-label={t("knowledgeBase.button.removeKb", {
                        name,
                      })}
                    >
                      ×
                    </button>
                  </span>
                );
              })}
            </div>
          )}
        </div>

        {knowledgeBases.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={t("chat.knowledgeScope.empty")}
          />
        ) : (
          <div className="max-h-80 divide-y divide-border overflow-y-auto">
            {knowledgeBases.map((knowledgeBase) => {
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
                <div
                  role="button"
                  tabIndex={disabledByModel ? -1 : 0}
                  key={id}
                  className={`flex w-full items-start gap-3 px-4 ${KB_LAYOUT.ROW_PADDING} text-left transition-colors ${
                    disabledByModel
                      ? "cursor-not-allowed bg-muted/30 opacity-50"
                      : "hover:bg-muted/40"
                  }`}
                  onClick={() => {
                    if (!disabledByModel) {
                      toggleKnowledgeBase(source, id);
                    }
                  }}
                  onKeyDown={(event) => {
                    if (
                      !disabledByModel &&
                      (event.key === "Enter" || event.key === " ")
                    ) {
                      event.preventDefault();
                      toggleKnowledgeBase(source, id);
                    }
                  }}
                  aria-disabled={disabledByModel}
                  title={
                    disabledByModel
                      ? t("chat.knowledgeScope.embeddingMismatch")
                      : undefined
                  }
                >
                  <Checkbox
                    checked={isSelected}
                    disabled={disabledByModel}
                    className="mt-1"
                    onClick={(event) => event.stopPropagation()}
                    onChange={() => toggleKnowledgeBase(source, id)}
                  />
                  <div className="min-w-0 flex-1">
                    <div
                      className={`${KB_LAYOUT.KB_NAME_TEXT} truncate text-foreground`}
                      title={name}
                    >
                      {name}
                    </div>
                    {source === "aidp" && (
                      <div
                        className="mt-1 line-clamp-2 text-xs text-muted-foreground"
                        title={
                          knowledgeBase.description ||
                          t("aidpKnowledge.noDescription")
                        }
                      >
                        {knowledgeBase.description ||
                          t("aidpKnowledge.noDescription")}
                      </div>
                    )}
                    <div
                      className={`flex flex-wrap items-center ${KB_LAYOUT.TAG_MARGIN} ${KB_LAYOUT.TAG_SPACING}`}
                    >
                      {source === "local" &&
                        knowledgeBase.embeddingModel &&
                        knowledgeBase.embeddingModel !== "unknown" && (
                          <span
                            className={`${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_TAG_VARIANTS.model}`}
                          >
                            {t("knowledgeBase.tag.model", {
                              model: knowledgeBase.embeddingModel,
                            })}
                          </span>
                        )}
                      {source === "aidp" && (
                        <span
                          className={`${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_TAG_VARIANTS.default}`}
                        >
                          {knowledgeBase.createdAt
                            ? t("aidpKnowledge.createdAt", {
                                date: new Date(
                                  knowledgeBase.createdAt
                                ).toLocaleDateString(),
                              })
                            : t("aidpKnowledge.createdAtUnknown")}
                        </span>
                      )}
                      {knowledgeBase.ingroup_permission === "PRIVATE" ? (
                        <span
                          className={`${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_TAG_VARIANTS.default}`}
                        >
                          {t("knowledgeBase.ingroup.permission.PRIVATE")}
                        </span>
                      ) : (
                        <Can permission="group:read">
                          {groupNames.map((groupName) => (
                            <span
                              key={groupName}
                              className={`${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} border border-blue-200 bg-blue-100 text-blue-800`}
                            >
                              {groupName}
                            </span>
                          ))}
                        </Can>
                      )}
                      {knowledgeBase.is_multimodal && (
                        <span
                          className={`${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_TAG_VARIANTS.red}`}
                        >
                          multimodal
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
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
      width={720}
      footer={(_, { OkBtn, CancelBtn }) => (
        <div className="flex items-center justify-between">
          <button
            type="button"
            className="text-sm text-muted-foreground hover:text-foreground"
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
          </button>
          <div className="flex gap-2">
            <CancelBtn />
            <OkBtn />
          </div>
        </div>
      )}
    >
      {value &&
        ((value.local.mode === "override" &&
          !capabilities?.sources.local.enabled) ||
          (value.aidp.mode === "override" &&
            !capabilities?.sources.aidp.enabled)) && (
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
      <Spin spinning={loading}>
        {configuredSource ? (
          <div className="space-y-3 py-2">{renderSource(configuredSource)}</div>
        ) : hasSourceConflict ? (
          <Alert
            type="error"
            showIcon
            message={t("chat.knowledgeScope.sourceConflict")}
          />
        ) : (
          <Empty description={t("chat.knowledgeScope.noTool")} />
        )}
      </Spin>
    </Modal>
  );
};
