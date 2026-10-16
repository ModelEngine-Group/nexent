// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button } from "antd";
import { Pencil, Settings, Tag } from "lucide-react";

import { ResourceDrawer } from "./ResourceDrawer";
import { useSkillList } from "@/hooks/agent/useSkillList";
import log from "@/lib/logger";
import { ResourceCollection, ResourceItem } from "./ResourceItem";
import { fetchSkillInstances } from "@/services/agentConfigService";
import type { Skill, SkillGroup, SkillParam } from "@/types/agentConfig";
import SkillConfigModal from "@/components/skill-config/SkillConfigModal";

import { useResourceTagFilter } from "@/hooks/useResourceTagFilter";
import { ResourceTagFilterControl } from "./ResourceTagFilterControl";
import { ResourceAssignedTags } from "./ResourceAssignedTags";
import { ResourceTagManagementModal } from "./ResourceTagManagementModal";

import styles from "./ResourcePickerDrawer.module.css";

// ---- Skill config helpers (inlined from capability/skill/utils.ts) ----
const isMissingRequiredValue = (value: unknown): boolean =>
  value === undefined || value === null || value === "";

const getEffectiveParamValue = (
  param: SkillParam,
  configValues: Record<string, unknown>
): unknown =>
  Object.prototype.hasOwnProperty.call(configValues, param.name)
    ? configValues[param.name]
    : param.value;

const withEffectiveSkillConfig = (
  skill: Skill,
  savedConfigValues?: Record<string, unknown> | null
): Skill => {
  const schemaDefaults = Object.fromEntries(
    (skill.config_schemas || []).map((param) => [param.name, param.value])
  );
  const skillConfigValues =
    skill.config_values && typeof skill.config_values === "object"
      ? skill.config_values
      : {};

  return {
    ...skill,
    config_values: {
      ...schemaDefaults,
      ...skillConfigValues,
      ...(savedConfigValues || {}),
    },
  };
};

const hasMissingRequiredSkillConfig = (skill: Skill): boolean => {
  const configValues =
    skill.config_values && typeof skill.config_values === "object"
      ? skill.config_values
      : {};

  return (skill.config_schemas || []).some(
    (param) =>
      param.required &&
      isMissingRequiredValue(getEffectiveParamValue(param, configValues))
  );
};

const requiresSkillConfigOnSelection = (skill: Skill): boolean =>
  skill.name.toLowerCase() === "search-knowledge-base";

export interface SkillDrawerProps {
  open: boolean;
  onClose: () => void;
  selectedSkills: Skill[];
  onConfirm: (skills: Skill[]) => void | Promise<void>;
  groups?: SkillGroup[];
  onRefresh?: () => void;
  onOpenManageTags?: () => void;
  enableTagManagement?: boolean;
  onOpenTagManagement?: () => void;
  onEditSkill?: (skill: Skill) => void;
  currentAgentId?: number;
  isReadOnly?: boolean;
}

const includesText = (value: string | null | undefined, query: string) =>
  value?.toLowerCase().includes(query) ?? false;

const matchesSkillFilters = (skill: Skill, query: string) => {
  const matchesText =
    !query ||
    includesText(skill.name, query) ||
    includesText(skill.description, query) ||
    (skill.tags || []).some((tag) => includesText(tag, query));

  return matchesText;
};

export function SkillDrawer({
  open,
  onClose,
  selectedSkills,
  onConfirm,
  groups,
  onRefresh,
  onOpenManageTags,
  enableTagManagement = false,
  onOpenTagManagement,
  onEditSkill,
  currentAgentId,
  isReadOnly,
}: SkillDrawerProps) {
  const { t } = useTranslation("common");
  const [tagManagementOpen, setTagManagementOpen] = useState(false);
  const [previousOpen, setPreviousOpen] = useState(open);
  if (previousOpen !== open) {
    setPreviousOpen(open);
    if (!open) setTagManagementOpen(false);
  }
  const catalog = useSkillList({ enabled: open && groups === undefined });
  const groupedSkills = groups ?? catalog.groupedSkills;
  const availableSkills = useMemo(
    () => groupedSkills.flatMap((group) => group.skills),
    [groupedSkills]
  );
  const resourceTags = useResourceTagFilter(
    open,
    "skill",
    availableSkills.map((skill) => String(skill.skill_id))
  );
  const invalidate = onRefresh ?? catalog.invalidate;
  const [search, setSearch] = useState("");
  const [activeTab, setActiveTab] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [configSkill, setConfigSkill] = useState<Skill | null>(null);
  const [skillInstanceMap, setSkillInstanceMap] = useState<
    Record<string, Record<string, unknown>>
  >({});

  // Local draft of the selected skills. Changes are only committed to the
  // agent store when the confirm button is clicked.
  const [draftSkills, setDraftSkills] = useState<Skill[]>([]);

  const sessionOpen = useRef(false);
  const confirming = useRef(false);
  const [saving, setSaving] = useState(false);
  const [confirmError, setConfirmError] = useState<string>();
  useEffect(() => {
    if (open && !sessionOpen.current) {
      setDraftSkills(selectedSkills);
      setConfirmError(undefined);
    }
    sessionOpen.current = open;
  }, [open, selectedSkills]);

  const selectedSkillIds = useMemo(
    () => new Set(draftSkills.map((skill) => Number(skill.skill_id))),
    [draftSkills]
  );

  const filteredGroups = useMemo<SkillGroup[]>(() => {
    const query = search.trim().toLowerCase();
    return groupedSkills
      .map((group) => ({
        ...group,
        skills: group.skills.filter(
          (skill: Skill) =>
            matchesSkillFilters(skill, query) &&
            (!resourceTags.matchedIds ||
              resourceTags.matchedIds.has(String(skill.skill_id)))
        ),
      }))
      .filter((group) => group.skills.length > 0);
  }, [groupedSkills, search, resourceTags.matchedIds]);

  const tabItems = useMemo(
    () =>
      groupedSkills.map((group) => ({
        key: group.key,
        label: group.label,
      })),
    [groupedSkills]
  );

  const activeGroup = useMemo(
    () => filteredGroups.find((group) => group.key === activeTab),
    [activeTab, filteredGroups]
  );
  const selectableSkillsInActiveGroup = useMemo(
    () =>
      activeGroup?.skills.filter((skill) => {
        const configuredSkill = withEffectiveSkillConfig(
          skill,
          skillInstanceMap[skill.skill_id]
        );
        return (
          !requiresSkillConfigOnSelection(configuredSkill) &&
          !hasMissingRequiredSkillConfig(configuredSkill)
        );
      }) || [],
    [activeGroup, skillInstanceMap]
  );
  const allVisibleSkillsSelected = useMemo(
    () =>
      selectableSkillsInActiveGroup.length > 0 &&
      selectableSkillsInActiveGroup.every((skill) =>
        selectedSkillIds.has(Number(skill.skill_id))
      ),
    [selectableSkillsInActiveGroup, selectedSkillIds]
  );

  const skillMetadataModifiable = useMemo(
    () => availableSkills.some((skill: Skill) => skill.permission === "EDIT"),
    [availableSkills]
  );

  const selectedChips = useMemo(() => {
    // Agent detail returns persisted skill instances (skill_name field) rather
    // than catalog entries (name field). Resolve the display name by merging
    // with the catalog like SelectedSkillManagement does.
    const catalogSkills = availableSkills as Skill[];
    const catalogById = new Map(
      catalogSkills.map((skill: Skill) => [Number(skill.skill_id), skill])
    );
    return draftSkills.map((skill) => {
      const persistedSkill = skill as Skill & { skill_name?: string };
      const canonicalSkill = catalogById.get(Number(skill.skill_id));
      return {
        id: String(skill.skill_id),
        label:
          skill.name || persistedSkill.skill_name || canonicalSkill?.name || "",
      };
    });
  }, [availableSkills, draftSkills]);

  const total = activeGroup?.skills.length ?? 0;
  const pagedSkills = useMemo(() => {
    const skills = activeGroup?.skills ?? [];
    return skills.slice((page - 1) * pageSize, page * pageSize);
  }, [activeGroup, page, pageSize]);

  useEffect(() => {
    if (!open || groupedSkills.length === 0) return;

    const visibleGroupKeys = filteredGroups.map((group) => group.key);
    if (!activeTab || !visibleGroupKeys.includes(activeTab)) {
      setActiveTab(visibleGroupKeys[0] || groupedSkills[0].key);
    }
  }, [activeTab, filteredGroups, groupedSkills, open]);

  useEffect(() => {
    setPage(1);
  }, [activeTab, search, resourceTags.matchedIds]);

  useEffect(() => {
    if (!open || !currentAgentId) {
      setSkillInstanceMap({});
      return;
    }

    let cancelled = false;
    const loadSkillInstances = async () => {
      try {
        const result = await fetchSkillInstances(Number(currentAgentId), 0);
        if (!result.success || !result.data || cancelled) return;

        const instanceMap: Record<string, Record<string, unknown>> = {};
        result.data.forEach(
          (instance: {
            skill_id: string;
            config_values?: Record<string, unknown> | null;
          }) => {
            if (
              instance.config_values &&
              typeof instance.config_values === "object"
            ) {
              instanceMap[instance.skill_id] = instance.config_values;
            }
          }
        );
        setSkillInstanceMap(instanceMap);
      } catch (error) {
        log.error("Failed to fetch skill instances:", error);
      }
    };

    void loadSkillInstances();
    return () => {
      cancelled = true;
    };
  }, [currentAgentId, open]);

  const toggleSkill = useCallback(
    (skill: Skill) => {
      if (isReadOnly) return;

      const isSelected = draftSkills.some(
        (selectedSkill) =>
          Number(selectedSkill.skill_id) === Number(skill.skill_id)
      );

      if (isSelected) {
        setDraftSkills((current) =>
          current.filter(
            (selectedSkill) =>
              Number(selectedSkill.skill_id) !== Number(skill.skill_id)
          )
        );
        return;
      }

      const configuredSkill = withEffectiveSkillConfig(
        skill,
        skillInstanceMap[skill.skill_id]
      );

      if (
        requiresSkillConfigOnSelection(configuredSkill) ||
        hasMissingRequiredSkillConfig(configuredSkill)
      ) {
        setConfigSkill(configuredSkill);
        return;
      }

      setDraftSkills((current) => [...current, configuredSkill]);
    },
    [isReadOnly, skillInstanceMap, draftSkills]
  );

  const removeSkill = useCallback(
    (id: string) => {
      if (isReadOnly) return;
      setDraftSkills((current) =>
        current.filter((skill) => Number(skill.skill_id) !== Number(id))
      );
    },
    [isReadOnly]
  );

  const selectAllVisibleSkills = useCallback(() => {
    if (isReadOnly || selectableSkillsInActiveGroup.length === 0) return;

    const skillsToAdd = selectableSkillsInActiveGroup
      .filter((skill) => !selectedSkillIds.has(Number(skill.skill_id)))
      .map((skill) =>
        withEffectiveSkillConfig(skill, skillInstanceMap[skill.skill_id])
      );

    if (skillsToAdd.length > 0) {
      setDraftSkills((current) => [...current, ...skillsToAdd]);
    }
  }, [
    isReadOnly,
    selectableSkillsInActiveGroup,
    skillInstanceMap,
    selectedSkillIds,
  ]);

  const deselectAllVisibleSkills = useCallback(() => {
    if (isReadOnly || !activeGroup) return;

    const visibleSkillIds = new Set(
      activeGroup.skills.map((skill) => Number(skill.skill_id))
    );
    setDraftSkills((current) =>
      current.filter((skill) => !visibleSkillIds.has(Number(skill.skill_id)))
    );
  }, [activeGroup, isReadOnly]);

  const handleSelectAll = useCallback(
    (checked: boolean) => {
      if (checked) selectAllVisibleSkills();
      else deselectAllVisibleSkills();
    },
    [selectAllVisibleSkills, deselectAllVisibleSkills]
  );

  const openSkillConfig = useCallback(
    (skill: Skill, event: React.MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      setConfigSkill(
        withEffectiveSkillConfig(skill, skillInstanceMap[skill.skill_id])
      );
    },
    [skillInstanceMap]
  );

  const saveSkillConfig = useCallback((skill: Skill, params: SkillParam[]) => {
    const configValues = Object.fromEntries(
      params.map((param) => [param.name, param.value])
    );
    setSkillInstanceMap((current) => ({
      ...current,
      [skill.skill_id]: configValues,
    }));

    const configuredSkill = { ...skill, config_values: configValues };
    setDraftSkills((current) => {
      const selectedIndex = current.findIndex(
        (selectedSkill) =>
          Number(selectedSkill.skill_id) === Number(skill.skill_id)
      );

      if (selectedIndex < 0) {
        return [...current, configuredSkill];
      }

      const updatedSkills = [...current];
      updatedSkills[selectedIndex] = configuredSkill;
      return updatedSkills;
    });
  }, []);

  const onCloseDialog = useCallback(() => {
    setSearch("");
    setActiveTab("");
    setPage(1);
    onClose();
  }, [onClose]);

  const handleConfirm = async () => {
    if (confirming.current || isReadOnly) return;
    confirming.current = true;
    setSaving(true);
    setConfirmError(undefined);
    try {
      await onConfirm(draftSkills);
      onCloseDialog();
    } catch (error) {
      setConfirmError(
        error instanceof Error
          ? error.message
          : t("resourcePicker.selectionFailed", "选择失败，请重试")
      );
    } finally {
      confirming.current = false;
      setSaving(false);
    }
  };

  return (
    <ResourceDrawer
      width="min(768px, 100vw)"
      bodyClassName={styles.drawer}
      title={t("resourcePicker.addSkill", "添加技能")}
      open={open}
      searchPlaceholder={t("skillPool.searchSkillsPlaceholder")}
      tagFilter={
        <ResourceTagFilterControl
          filter={resourceTags}
          onChange={() => setPage(1)}
        />
      }
      selected={selectedChips}
      listTitle={t("resourcePicker.list.skill")}
      tagManagement={
        onOpenManageTags || enableTagManagement
          ? {
              onClick: onOpenManageTags ?? (() => setTagManagementOpen(true)),
              disabled: isReadOnly || !skillMetadataModifiable,
            }
          : undefined
      }
      listHeaderExtra={
        onOpenTagManagement ? (
          <Button
            type="text"
            size="small"
            icon={<Tag size={14} />}
            disabled={isReadOnly || !skillMetadataModifiable}
            onClick={onOpenTagManagement}
          >
            {t("tagManagement.title.definitionManagement")}
          </Button>
        ) : undefined
      }
      tabs={tabItems}
      activeTab={activeTab}
      total={total}
      page={page}
      onClose={onCloseDialog}
      onConfirm={() => void handleConfirm()}
      confirmLoading={saving}
      confirmDisabled={
        isReadOnly ||
        resourceTags.filtering ||
        !!(resourceTags.predicates.length && resourceTags.error)
      }
      keyword={search}
      controlsContent={
        confirmError ? <Alert type="error" title={confirmError} /> : undefined
      }
      onSearch={setSearch}
      onTabChange={setActiveTab}
      onRemoveSelected={removeSkill}
      onSelectAll={handleSelectAll}
      allSelected={allVisibleSkillsSelected}
      onRefresh={() => void invalidate()}
      onPageChange={setPage}
      pageSize={pageSize}
      onPageSizeChange={(size) => {
        setPageSize(size);
        setPage(1);
      }}
    >
      {activeGroup ? (
        <ResourceCollection>
          {pagedSkills.map((skill) => {
            const isSelected = selectedSkillIds.has(Number(skill.skill_id));
            const hasConfigurableParams =
              Array.isArray(skill.config_schemas) &&
              skill.config_schemas.length > 0;

            return (
              <ResourceItem
                key={skill.skill_id}
                item={{
                  key: String(skill.skill_id),
                  name: skill.name,
                  description: skill.description,
                  tags: skill.tags,
                  raw: skill,
                }}
                selected={isSelected}
                disabled={isReadOnly || saving}
                onToggle={() => toggleSkill(skill)}
                slots={{
                  renderTags: () => (
                    <ResourceAssignedTags
                      resourceType="skill"
                      resourceId={String(skill.skill_id)}
                      tags={skill.tags}
                      refreshKey={resourceTags.revision}
                    />
                  ),
                  renderActions: () => (
                    <div className="flex items-center gap-1">
                      {onEditSkill && (
                        <button
                          type="button"
                          disabled={
                            isReadOnly || saving || skill.permission !== "EDIT"
                          }
                          onClick={() => onEditSkill(skill)}
                          aria-label={t("skillManagement.edit.title")}
                          title={t("skillManagement.edit.title")}
                          className="flex size-7 shrink-0 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 disabled:cursor-not-allowed disabled:opacity-40"
                        >
                          <Pencil className="size-4" />
                        </button>
                      )}
                      <button
                        type="button"
                        disabled={
                          isReadOnly || saving || !hasConfigurableParams
                        }
                        onClick={(event) => openSkillConfig(skill, event)}
                        aria-label={t("skillPool.configure")}
                        title={t(
                          hasConfigurableParams
                            ? "skillPool.configure"
                            : "resourcePicker.skill.noParameters"
                        )}
                        className="flex size-7 shrink-0 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        <Settings className="size-4" />
                      </button>
                    </div>
                  ),
                }}
              />
            );
          })}
        </ResourceCollection>
      ) : (
        <div className="flex flex-1 items-center justify-center text-sm text-gray-400">
          {t("skillPool.noSearchResults")}
        </div>
      )}

      {tagManagementOpen && (
        <ResourceTagManagementModal
          resourceType="skill"
          resources={availableSkills.map((skill) => ({
            id: String(skill.skill_id),
            name: skill.name,
            canEdit: !isReadOnly && skill.permission === "EDIT",
          }))}
          definitions={resourceTags.definitions}
          onClose={() => {
            setTagManagementOpen(false);
            resourceTags.retry();
          }}
          onSaved={() => resourceTags.retry()}
        />
      )}

      {configSkill ? (
        <SkillConfigModal
          isOpen
          onCancel={() => setConfigSkill(null)}
          onSave={(params) => saveSkillConfig(configSkill, params)}
          skill={configSkill}
          initialParams={configSkill.config_schemas || []}
          currentAgentId={currentAgentId}
          zIndex={1100}
          maskClosable
        />
      ) : null}
    </ResourceDrawer>
  );
}
