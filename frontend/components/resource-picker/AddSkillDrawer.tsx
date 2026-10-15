// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "antd";
import { Settings, Tag } from "lucide-react";

import { AddResourceDrawer, CheckMark } from "./AddResourceDrawer";
import { useSkillList } from "@/hooks/agent/useSkillList";
import log from "@/lib/logger";
import { cn } from "@/lib/utils";
import { fetchSkillInstances } from "@/services/agentConfigService";
import { useAgentStore } from "@/stores/agentStore";
import type { Skill, SkillGroup, SkillParam } from "@/types/agentConfig";
import SkillConfigModal from "@/app/agents/components/capability/skill/SkillConfigModal";

import styles from "./ResourcePickerDrawer.module.css";

const PAGE_SIZE = 10;

// Stable fallback so the zustand selector returns a referentially-stable value
// when `editedAgent?.skills` is undefined (avoids a getSnapshot infinite loop).
const EMPTY_SKILLS: Skill[] = [];

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

export interface AddSkillDrawerProps {
  open: boolean;
  onClose: () => void;
  onOpenManageTags?: () => void;
  onOpenTagManagement?: () => void;
  currentAgentId?: number;
  isReadOnly?: boolean;
}

const includesText = (value: string | null | undefined, query: string) =>
  value?.toLowerCase().includes(query) ?? false;

const matchesSkillFilters = (
  skill: Skill,
  query: string,
  activeTag: string
) => {
  const matchesText =
    !query ||
    includesText(skill.name, query) ||
    includesText(skill.description, query) ||
    (skill.tags || []).some((tag) => includesText(tag, query));
  const matchesTag = !activeTag || (skill.tags || []).includes(activeTag);

  return matchesText && matchesTag;
};

export function AddSkillDrawer({
  open,
  onClose,
  onOpenManageTags,
  onOpenTagManagement,
  currentAgentId,
  isReadOnly,
}: AddSkillDrawerProps) {
  const { t } = useTranslation("common");
  const { groupedSkills, availableSkills, invalidate } = useSkillList({
    enabled: open,
  });
  const [search, setSearch] = useState("");
  const [activeTag, setActiveTag] = useState("");
  const [activeTab, setActiveTab] = useState("");
  const [page, setPage] = useState(1);
  const [configSkill, setConfigSkill] = useState<Skill | null>(null);
  const [skillInstanceMap, setSkillInstanceMap] = useState<
    Record<string, Record<string, unknown>>
  >({});

  const selectedSkills = useAgentStore(
    (state) => state.editedAgent?.skills ?? EMPTY_SKILLS
  );
  const updateSkills = useAgentStore((state) => state.updateSkills);

  // Local draft of the selected skills. Changes are only committed to the
  // agent store when the confirm button is clicked.
  const [draftSkills, setDraftSkills] = useState<Skill[]>([]);

  useEffect(() => {
    if (!open) return;
    setDraftSkills(selectedSkills);
  }, [open, selectedSkills]);

  const selectedSkillIds = useMemo(
    () => new Set(draftSkills.map((skill) => Number(skill.skill_id))),
    [draftSkills]
  );

  const allTags = useMemo(() => {
    const tagSet = new Set<string>();
    availableSkills.forEach((skill: Skill) =>
      (skill.tags || []).forEach((tag: string) => tagSet.add(tag))
    );
    return [...tagSet].sort((left, right) => left.localeCompare(right));
  }, [availableSkills]);

  const tagOptions = useMemo(
    () => allTags.map((tag) => ({ value: tag, label: tag })),
    [allTags]
  );

  const filteredGroups = useMemo<SkillGroup[]>(() => {
    const query = search.trim().toLowerCase();
    return groupedSkills
      .map((group) => ({
        ...group,
        skills: group.skills.filter((skill: Skill) =>
          matchesSkillFilters(skill, query, activeTag)
        ),
      }))
      .filter((group) => group.skills.length > 0);
  }, [activeTag, groupedSkills, search]);

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
    return skills.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  }, [activeGroup, page]);

  useEffect(() => {
    if (!open || groupedSkills.length === 0) return;

    const visibleGroupKeys = filteredGroups.map((group) => group.key);
    if (!activeTab || !visibleGroupKeys.includes(activeTab)) {
      setActiveTab(visibleGroupKeys[0] || groupedSkills[0].key);
    }
  }, [activeTab, filteredGroups, groupedSkills, open]);

  useEffect(() => {
    setPage(1);
  }, [activeTab, search, activeTag]);

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
    setActiveTag("");
    setActiveTab("");
    setPage(1);
    onClose();
  }, [onClose]);

  const handleConfirm = useCallback(() => {
    updateSkills(draftSkills);
    onCloseDialog();
  }, [draftSkills, updateSkills, onCloseDialog]);

  return (
    <AddResourceDrawer
      width={768}
      bodyClassName={styles.drawer}
      title={
        <div className="flex min-w-0 items-center gap-2">
          <span className="min-w-0 flex-1 truncate">
            {t("resourcePicker.addSkill", "添加技能")}
          </span>
          {onOpenTagManagement ? (
            <Button
              type="text"
              size="small"
              icon={<Tag size={13} />}
              disabled={!skillMetadataModifiable}
              onClick={onOpenTagManagement}
              className="h-6 text-xs !text-purple-500 hover:!text-purple-600 hover:!bg-purple-50 disabled:!text-gray-400"
            >
              {t("tagManagement.title.definitionManagement")}
            </Button>
          ) : null}
        </div>
      }
      open={open}
      searchPlaceholder={t("skillPool.searchSkillsPlaceholder")}
      tagOptions={tagOptions}
      selected={selectedChips}
      listTitle={t("resourcePicker.list.skill")}
      listHeaderExtra={
        onOpenManageTags ? (
          <button
            type="button"
            disabled={!skillMetadataModifiable}
            onClick={onOpenManageTags}
            className="flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-[#2673E5] disabled:cursor-not-allowed disabled:text-[#B3B3B3]"
          >
            <Tag size={14} />
            {t("skillPool.manageTags")}
          </button>
        ) : undefined
      }
      tabs={tabItems}
      activeTab={activeTab}
      total={total}
      page={page}
      onClose={onCloseDialog}
      onConfirm={handleConfirm}
      onSearch={setSearch}
      onTagChange={(value) => setActiveTag(value ?? "")}
      onTabChange={setActiveTab}
      onRemoveSelected={removeSkill}
      onSelectAll={handleSelectAll}
      allSelected={allVisibleSkillsSelected}
      onRefresh={() => void invalidate()}
      onPageChange={setPage}
    >
      {activeGroup ? (
        <div className="flex flex-col gap-2">
          {pagedSkills.map((skill) => {
            const isSelected = selectedSkillIds.has(Number(skill.skill_id));
            const hasConfigurableParams =
              Array.isArray(skill.config_schemas) &&
              skill.config_schemas.length > 0;

            return (
              <div
                key={skill.skill_id}
                role="button"
                tabIndex={isReadOnly ? -1 : 0}
                className={cn(
                  "flex h-[59px] shrink-0 items-center justify-between gap-3 rounded-[4px] py-[9px] pl-5 pr-7 transition-colors",
                  isSelected ? "bg-[#E6F2FD]" : "bg-transparent",
                  isReadOnly
                    ? "cursor-not-allowed opacity-60"
                    : "cursor-pointer hover:bg-gray-50"
                )}
                onClick={isReadOnly ? undefined : () => toggleSkill(skill)}
                onKeyDown={(event) => {
                  if (
                    !isReadOnly &&
                    (event.key === "Enter" || event.key === " ")
                  ) {
                    event.preventDefault();
                    toggleSkill(skill);
                  }
                }}
              >
                <div className="flex min-w-0 flex-1 flex-col">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "truncate text-[14px] leading-[22px]",
                        isSelected
                          ? "font-medium text-[#0067D1]"
                          : "font-medium text-[#191919]"
                      )}
                    >
                      {skill.name}
                    </span>
                    {(skill.tags || []).slice(0, 2).map((tag) => (
                      <span
                        key={tag}
                        className="h-5 shrink-0 rounded-[2px] bg-[#F5F5F5] px-2 text-[12px] leading-[20px] text-[#393939]"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                  {skill.description ? (
                    <p className="m-0 truncate text-[14px] font-normal leading-[22px] text-[#777777]">
                      {skill.description}
                    </p>
                  ) : null}
                </div>
                <div
                  className="flex shrink-0 items-center gap-1"
                  data-testid={`skill-picker-actions-${skill.skill_id}`}
                >
                  {hasConfigurableParams ? (
                    <button
                      type="button"
                      disabled={isReadOnly}
                      onClick={(event) => openSkillConfig(skill, event)}
                      aria-label={t("skillPool.configure")}
                      title={t("skillPool.configure")}
                      className="flex size-7 shrink-0 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <Settings className="size-4" />
                    </button>
                  ) : null}
                </div>
                <CheckMark checked={isSelected} />
              </div>
            );
          })}
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center text-sm text-gray-400">
          {t("skillPool.noSearchResults")}
        </div>
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
    </AddResourceDrawer>
  );
}
