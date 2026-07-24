"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Input, Modal, Select, Tabs } from "antd";
import { BlocksIcon, Info, Search, Settings, Tag } from "lucide-react";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useSkillList } from "@/hooks/agent/useSkillList";
import log from "@/lib/logger";
import { fetchSkillInstances } from "@/services/agentConfigService";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import type { Skill, SkillGroup, SkillParam } from "@/types/agentConfig";
import SkillDetailModal from "../SkillDetailModal";
import SkillConfigModal from "./SkillConfigModal";
import SkillRowContent from "./SkillRowContent";

interface SelectSkillsDialogProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly onOpenManageTags: () => void;
  readonly isCreatingMode?: boolean;
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

const skillTagManagementEnabled = false;

export default function SelectSkillsDialog({
  open,
  onClose,
  onOpenManageTags,
  isCreatingMode,
  currentAgentId,
  isReadOnly,
}: SelectSkillsDialogProps) {
  const { t } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const { groupedSkills, availableSkills } = useSkillList({ enabled: open });
  const [search, setSearch] = useState("");
  const [activeTags, setActiveTags] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState("");
  const [detailSkill, setDetailSkill] = useState<Skill | null>(null);
  const [configSkill, setConfigSkill] = useState<Skill | null>(null);
  const [skillInstanceMap, setSkillInstanceMap] = useState<
    Record<string, Record<string, unknown>>
  >({});

  const selectedSkills = useAgentConfigStore(
    (state) => state.editedAgent.skills
  );
  const updateSkills = useAgentConfigStore((state) => state.updateSkills);
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

  const skillMetadataModifiable = useMemo(
    () =>
      availableSkills.some((skill: Skill) =>
        Boolean(user?.id && skill.created_by === user.id)
      ),
    [availableSkills, user?.id]
  );

  useEffect(() => {
    if (!open || groupedSkills.length === 0) return;

    const visibleGroupKeys = filteredGroups.map((group) => group.key);
    if (!activeTab || !visibleGroupKeys.includes(activeTab)) {
      setActiveTab(visibleGroupKeys[0] || groupedSkills[0].key);
    }
  }, [activeTab, filteredGroups, groupedSkills, open]);

  useEffect(() => {
    if (!open || !currentAgentId || isCreatingMode) {
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
  }, [currentAgentId, isCreatingMode, open]);

  const toggleSkill = useCallback(
    (skill: Skill) => {
      if (isReadOnly) return;

      const currentSkills = useAgentConfigStore.getState().editedAgent.skills;
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

      updateSkills([
        ...currentSkills,
        {
          ...skill,
          config_values:
            skillInstanceMap[skill.skill_id] || skill.config_values || {},
        },
      ]);
    },
    [isReadOnly, skillInstanceMap, updateSkills]
  );

  const openSkillInfo = useCallback(
    (skill: Skill, event: React.MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      setDetailSkill(skill);
    },
    []
  );

  const openSkillConfig = useCallback(
    (skill: Skill, event: React.MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      setConfigSkill({
        ...skill,
        config_values:
          skillInstanceMap[skill.skill_id] || skill.config_values || {},
      });
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

      const currentSkills = useAgentConfigStore.getState().editedAgent.skills;
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
            disabled={!skillTagManagementEnabled || !skillMetadataModifiable}
            onClick={onOpenManageTags}
            className="h-6 text-xs !text-purple-500 hover:!text-purple-600 hover:!bg-purple-50 disabled:!text-gray-400"
          >
            {t("skillPool.manageTags")}
          </Button>
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
      </div>
      <div className="flex h-[55vh] min-h-[340px] max-h-[55vh] gap-3 overflow-hidden">
        {activeGroup ? (
          <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
            {activeGroup.skills.map((skill) => {
              const isSelected = selectedSkillIds.has(Number(skill.skill_id));
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
                      className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
                      data-testid={`skill-picker-actions-${skill.skill_id}`}
                    >
                      <button
                        type="button"
                        onClick={(event) => openSkillInfo(skill, event)}
                        aria-label={t("skillPool.viewDetails")}
                        title={t("skillPool.viewDetails")}
                        className="flex size-7 shrink-0 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
                      >
                        <Info className="size-4" />
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
          isCreatingMode={isCreatingMode}
          zIndex={1100}
          maskClosable
        />
      ) : null}
    </Modal>
  );
}
