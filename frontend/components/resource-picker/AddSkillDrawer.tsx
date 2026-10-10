"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "antd";
import { BlocksIcon, Eye, Pencil, Settings, Tag } from "lucide-react";

import { AddResourceDrawer, CheckMark } from "./AddResourceDrawer";
import { useSkillList } from "@/hooks/agent/useSkillList";
import log from "@/lib/logger";
import { cn } from "@/lib/utils";
import { fetchSkillInstances } from "@/services/agentConfigService";
import { useAgentStore } from "@/stores/agentStore";
import type { Skill, SkillGroup, SkillParam } from "@/types/agentConfig";
import SkillDetailModal from "@/app/agents/components/capability/SkillDetailModal";
import SkillConfigModal from "@/app/agents/components/capability/skill/SkillConfigModal";

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
  onEditSkill?: (skill: Skill) => void;
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
  onEditSkill,
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
  const [detailSkill, setDetailSkill] = useState<Skill | null>(null);
  const [configSkill, setConfigSkill] = useState<Skill | null>(null);
  const [skillInstanceMap, setSkillInstanceMap] = useState<
    Record<string, Record<string, unknown>>
  >({});

  const selectedSkills = useAgentStore(
    (state) => state.editedAgent?.skills ?? EMPTY_SKILLS
  );
  const updateSkills = useAgentStore((state) => state.updateSkills);
  const selectedSkillIds = useMemo(
    () => new Set(selectedSkills.map((skill) => Number(skill.skill_id))),
    [selectedSkills]
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
    return selectedSkills.map((skill) => {
      const persistedSkill = skill as Skill & { skill_name?: string };
      const canonicalSkill = catalogById.get(Number(skill.skill_id));
      return {
        id: String(skill.skill_id),
        label:
          skill.name ||
          persistedSkill.skill_name ||
          canonicalSkill?.name ||
          "",
      };
    });
  }, [availableSkills, selectedSkills]);

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

      const currentSkills = useAgentStore.getState().editedAgent?.skills ?? [];
      const isSelected = currentSkills.some(
        (selectedSkill) =>
          Number(selectedSkill.skill_id) === Number(skill.skill_id)
      );

      if (isSelected) {
        updateSkills(
          currentSkills.filter(
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

      updateSkills([...currentSkills, configuredSkill]);
    },
    [isReadOnly, skillInstanceMap, updateSkills]
  );

  const removeSkill = useCallback(
    (id: string) => {
      if (isReadOnly) return;
      const currentSkills = useAgentStore.getState().editedAgent?.skills ?? [];
      updateSkills(
        currentSkills.filter(
          (skill) => Number(skill.skill_id) !== Number(id)
        )
      );
    },
    [isReadOnly, updateSkills]
  );

  const selectAllVisibleSkills = useCallback(() => {
    if (isReadOnly || selectableSkillsInActiveGroup.length === 0) return;

    const currentSkills = useAgentStore.getState().editedAgent?.skills ?? [];
    const currentSkillIds = new Set(
      currentSkills.map((skill) => Number(skill.skill_id))
    );
    const skillsToAdd = selectableSkillsInActiveGroup
      .filter((skill) => !currentSkillIds.has(Number(skill.skill_id)))
      .map((skill) =>
        withEffectiveSkillConfig(skill, skillInstanceMap[skill.skill_id])
      );

    if (skillsToAdd.length > 0) {
      updateSkills([...currentSkills, ...skillsToAdd]);
    }
  }, [
    isReadOnly,
    selectableSkillsInActiveGroup,
    skillInstanceMap,
    updateSkills,
  ]);

  const deselectAllVisibleSkills = useCallback(() => {
    if (isReadOnly || !activeGroup) return;

    const visibleSkillIds = new Set(
      activeGroup.skills.map((skill) => Number(skill.skill_id))
    );
    const currentSkills = useAgentStore.getState().editedAgent?.skills ?? [];
    updateSkills(
      currentSkills.filter(
        (skill) => !visibleSkillIds.has(Number(skill.skill_id))
      )
    );
  }, [activeGroup, isReadOnly, updateSkills]);

  const handleSelectAll = useCallback(
    (checked: boolean) => {
      if (checked) selectAllVisibleSkills();
      else deselectAllVisibleSkills();
    },
    [selectAllVisibleSkills, deselectAllVisibleSkills]
  );

  const openSkillAction = useCallback(
    (skill: Skill, event: React.MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      if (!isReadOnly && skill.permission === "EDIT" && onEditSkill) {
        onEditSkill(skill);
        return;
      }
      setDetailSkill(skill);
    },
    [isReadOnly, onEditSkill]
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

  const saveSkillConfig = useCallback(
    (skill: Skill, params: SkillParam[]) => {
      const configValues = Object.fromEntries(
        params.map((param) => [param.name, param.value])
      );
      setSkillInstanceMap((current) => ({
        ...current,
        [skill.skill_id]: configValues,
      }));

      const currentSkills = useAgentStore.getState().editedAgent?.skills ?? [];
      const configuredSkill = { ...skill, config_values: configValues };
      const selectedIndex = currentSkills.findIndex(
        (selectedSkill) =>
          Number(selectedSkill.skill_id) === Number(skill.skill_id)
      );

      if (selectedIndex < 0) {
        updateSkills([...currentSkills, configuredSkill]);
        return;
      }

      const updatedSkills = [...currentSkills];
      updatedSkills[selectedIndex] = configuredSkill;
      updateSkills(updatedSkills);
    },
    [updateSkills]
  );

  const onCloseDialog = useCallback(() => {
    setSearch("");
    setActiveTag("");
    setActiveTab("");
    setPage(1);
    onClose();
  }, [onClose]);

  return (
    <AddResourceDrawer
      title={
        <div className="flex items-center gap-2 pr-8">
          <BlocksIcon className="size-4" />
          <span className="flex-1">{t("skillPool.selectSkills")}</span>
          {onOpenManageTags ? (
            <Button
              type="text"
              size="small"
              icon={<Tag size={13} />}
              disabled={!skillMetadataModifiable}
              onClick={onOpenManageTags}
              className="h-6 text-xs !text-purple-500 hover:!text-purple-600 hover:!bg-purple-50 disabled:!text-gray-400"
            >
              {t("skillPool.manageTags")}
            </Button>
          ) : null}
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
      tabs={tabItems}
      activeTab={activeTab}
      total={total}
      page={page}
      showConfirm={false}
      onClose={onCloseDialog}
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
            const canEditSkill =
              !isReadOnly &&
              skill.permission === "EDIT" &&
              Boolean(onEditSkill);
            const hasConfigurableParams =
              Array.isArray(skill.config_schemas) &&
              skill.config_schemas.length > 0;

            return (
              <div
                key={skill.skill_id}
                role="button"
                tabIndex={isReadOnly ? -1 : 0}
                className={cn(
                  "flex shrink-0 items-center gap-3 rounded-[2px] px-5 py-[9px] transition-colors",
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
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "text-[14px] leading-[20px]",
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
                    <p className="truncate text-[14px] leading-[20px] text-[#737373]">
                      {skill.description}
                    </p>
                  ) : null}
                </div>
                <div
                  className="flex shrink-0 items-center gap-1"
                  data-testid={`skill-picker-actions-${skill.skill_id}`}
                >
                  <button
                    type="button"
                    onClick={(event) => openSkillAction(skill, event)}
                    aria-label={t(
                      canEditSkill
                        ? "skillManagement.edit.title"
                        : "skillPool.viewDetails"
                    )}
                    title={t(
                      canEditSkill
                        ? "skillManagement.edit.title"
                        : "skillPool.viewDetails"
                    )}
                    className="flex size-7 shrink-0 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
                  >
                    {canEditSkill ? (
                      <Pencil className="size-4" />
                    ) : (
                      <Eye className="size-4" />
                    )}
                  </button>
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

      <SkillDetailModal
        skill={detailSkill}
        open={Boolean(detailSkill)}
        zIndex={1100}
        maskClosable
        onClose={() => setDetailSkill(null)}
      />

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