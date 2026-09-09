"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input, Modal, Select, Tabs } from "antd";
import { BlocksIcon, Eye, Pencil, Search, Settings, Tag } from "lucide-react";

import { useSkillList } from "@/hooks/agent/useSkillList";
import log from "@/lib/logger";
import { fetchSkillInstances } from "@/services/agentConfigService";
import { useAgentStore } from "@/stores/agentStore";
import type { Skill, SkillGroup, SkillParam } from "@/types/agentConfig";
import SkillDetailModal from "../SkillDetailModal";
import SkillConfigModal from "./SkillConfigModal";
import SkillRowContent from "./SkillRowContent";
import {
  hasMissingRequiredSkillConfig,
  requiresSkillConfigOnSelection,
  withEffectiveSkillConfig,
} from "./utils";

interface SelectSkillsDialogProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly onOpenManageTags: () => void;
  readonly onOpenTagManagement?: () => void;
  readonly onEditSkill?: (skill: Skill) => void;
  readonly currentAgentId?: number;
  readonly isReadOnly?: boolean;
}

const includesText = (value: string | null | undefined, query: string) =>
  value?.toLowerCase().includes(query) ?? false;

const matchesSkillFilters = (
  skill: Skill,
  query: string,
  activeTags: readonly string[]
) => {
  const matchesText =
    !query ||
    includesText(skill.name, query) ||
    includesText(skill.description, query) ||
    (skill.tags || []).some((tag) => includesText(tag, query));
  const matchesTags =
    activeTags.length === 0 ||
    (skill.tags || []).some((tag) => activeTags.includes(tag));

  return matchesText && matchesTags;
};

export default function SelectSkillsDialog({
  open,
  onClose,
  onOpenManageTags,
  onOpenTagManagement,
  onEditSkill,
  currentAgentId,
  isReadOnly,
}: SelectSkillsDialogProps) {
  const { t } = useTranslation("common");
  const { groupedSkills, availableSkills } = useSkillList({ enabled: open });
  const [search, setSearch] = useState("");
  const [activeTags, setActiveTags] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState("");
  const [detailSkill, setDetailSkill] = useState<Skill | null>(null);
  const [configSkill, setConfigSkill] = useState<Skill | null>(null);
  const [skillInstanceMap, setSkillInstanceMap] = useState<
    Record<string, Record<string, unknown>>
  >({});

  const selectedSkills = useAgentStore(
    (state) => state.editedAgent?.skills ?? []
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

  const filteredGroups = useMemo<SkillGroup[]>(() => {
    const query = search.trim().toLowerCase();
    return groupedSkills
      .map((group) => ({
        ...group,
        skills: group.skills.filter((skill: Skill) =>
          matchesSkillFilters(skill, query, activeTags)
        ),
      }))
      .filter((group) => group.skills.length > 0);
  }, [activeTags, groupedSkills, search]);

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

  useEffect(() => {
    if (!open || groupedSkills.length === 0) return;

    const visibleGroupKeys = filteredGroups.map((group) => group.key);
    if (!activeTab || !visibleGroupKeys.includes(activeTab)) {
      setActiveTab(visibleGroupKeys[0] || groupedSkills[0].key);
    }
  }, [activeTab, filteredGroups, groupedSkills, open]);

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
    setActiveTags([]);
    setActiveTab("");
    onClose();
  }, [onClose]);

  return (
    <Modal
      title={
        <div className="flex items-center gap-2 pr-8">
          <BlocksIcon className="size-4" />
          <span className="flex-1">{t("skillPool.selectSkills")}</span>
          <Button
            type="text"
            size="small"
            icon={<Tag size={13} />}
            disabled={!skillMetadataModifiable}
            onClick={onOpenManageTags}
            className="h-6 text-xs !text-purple-500 hover:!text-purple-600 hover:!bg-purple-50 disabled:!text-gray-400"
          >
            {t("skillPool.bulkAssignTags")}
          </Button>
          {onOpenTagManagement ? (
            <Button
              type="text"
              size="small"
              icon={<Tag size={13} />}
              disabled={!skillMetadataModifiable}
              onClick={onOpenTagManagement}
              className="h-6 text-xs !text-purple-500 hover:!text-purple-600 hover:!bg-purple-50 disabled:!text-gray-400"
            >
              {t("skillPool.tagManagement")}
            </Button>
          ) : null}
        </div>
      }
      open={open}
      onCancel={onCloseDialog}
      footer={null}
      width={1100}
      zIndex={1000}
      maskClosable
      mask={{ closable: true }}
      destroyOnHidden
    >
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />

      <div className="mb-3 flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-2 top-1/2 size-4 -translate-y-1/2 text-gray-400" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("skillPool.searchSkillsPlaceholder")}
            className="pl-7"
            allowClear
          />
        </div>
        <Select
          mode="multiple"
          value={activeTags}
          onChange={setActiveTags}
          placeholder={t("skillPool.filterByTag")}
          className="min-w-[180px]"
          options={allTags.map((tag) => {
            const count = (
              groupedSkills.find((group) => group.key === activeTab)?.skills ||
              []
            ).filter((skill: Skill) => (skill.tags || []).includes(tag)).length;
            return { label: `${tag} (${count})`, value: tag };
          })}
          allowClear
          maxTagCount={1}
          notFoundContent={
            allTags.length === 0 ? t("skillPool.noTagsAssigned") : undefined
          }
        />
        <Button
          onClick={
            allVisibleSkillsSelected
              ? deselectAllVisibleSkills
              : selectAllVisibleSkills
          }
          disabled={isReadOnly || selectableSkillsInActiveGroup.length === 0}
        >
          {t(
            allVisibleSkillsSelected ? "common.deselectAll" : "common.selectAll"
          )}
        </Button>
      </div>
      <div className="flex h-[55vh] min-h-[340px] max-h-[55vh] gap-3 overflow-hidden">
        {activeGroup ? (
          <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
            {activeGroup.skills.map((skill) => {
              const isSelected = selectedSkillIds.has(Number(skill.skill_id));
              const canEditSkill =
                !isReadOnly &&
                skill.permission === "EDIT" &&
                Boolean(onEditSkill);
              const hasConfigurableParams =
                Array.isArray(skill.config_schemas) &&
                skill.config_schemas.length > 0;

              return (
                <li key={skill.skill_id}>
                  <div
                    role="button"
                    tabIndex={isReadOnly ? -1 : 0}
                    className={`group flex items-center gap-2 rounded-md px-2 py-1.5 transition-colors ${
                      isReadOnly
                        ? "cursor-not-allowed opacity-60"
                        : "cursor-pointer hover:bg-gray-50"
                    }`}
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
                    <SkillRowContent
                      skill={skill}
                      selected={isSelected}
                      isReadOnly={Boolean(isReadOnly)}
                    />
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
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="flex flex-1 items-center justify-center text-sm text-gray-400">
            {t("skillPool.noSearchResults")}
          </div>
        )}
      </div>

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
    </Modal>
  );
}
