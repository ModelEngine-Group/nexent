"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { SkillGroup, Skill } from "@/types/agentConfig";
import { Tabs } from "antd";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useSkillList } from "@/hooks/agent/useSkillList";
import { Info } from "lucide-react";
import SkillDetailModal from "./SkillDetailModal";

interface SkillManagementProps {
  skillGroups: SkillGroup[];
  isCreatingMode?: boolean;
  currentAgentId?: number | undefined;
}

export default function SkillManagement({
  skillGroups,
  isCreatingMode,
  currentAgentId,
}: SkillManagementProps) {
  const { t } = useTranslation("common");

  const currentAgentPermission = useAgentConfigStore(
    (state) => state.currentAgentPermission
  );

  const isReadOnly = !isCreatingMode && currentAgentId !== undefined && currentAgentPermission === "READ_ONLY";

  const editable = (currentAgentId || isCreatingMode) && !isReadOnly;

  const originalSelectedSkills = useAgentConfigStore(
    (state) => state.editedAgent.skills
  );
  const originalSelectedSkillIdsSet = new Set(
    originalSelectedSkills.map((skill) => skill.skill_id)
  );

  const updateSkills = useAgentConfigStore((state) => state.updateSkills);

  const { groupedSkills } = useSkillList();

  const [activeTabKey, setActiveTabKey] = useState<string>("");
  const [selectedSkill, setSelectedSkill] = useState<Skill | null>(null);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState<boolean>(false);

  useEffect(() => {
    if (groupedSkills.length > 0 && !activeTabKey) {
      setActiveTabKey(groupedSkills[0].key);
    }
  }, [groupedSkills, activeTabKey]);

  const handleSkillClick = (skill: Skill) => {
    if (!editable || isReadOnly) return;

    const currentSkills = useAgentConfigStore.getState().editedAgent.skills;
    const isCurrentlySelected = currentSkills.some(
      (s) => s.skill_id === skill.skill_id
    );

    if (isCurrentlySelected) {
      const newSelectedSkills = currentSkills.filter(
        (s) => s.skill_id !== skill.skill_id
      );
      updateSkills(newSelectedSkills);
    } else {
      const newSelectedSkills = [...currentSkills, skill];
      updateSkills(newSelectedSkills);
    }
  };

  const handleInfoClick = (skill: Skill, e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedSkill(skill);
    setIsDetailModalOpen(true);
  };

  const tabItems = skillGroups.map((group) => {
    const displayLabel =
      group.label.length > 7
        ? `${group.label.substring(0, 7)}...`
        : group.label;

    return {
      key: group.key,
      label: (
        <span
          style={{
            display: "block",
            maxWidth: "70px",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            textAlign: "left",
          }}
        >
          {displayLabel}
        </span>
      ),
      children: (
        <div
          className="flex flex-col gap-2 pr-2 flex-1"
          style={{
            overflowY: "auto",
            padding: "4px 0",
          }}
        >
          {group.skills.map((skill) => {
            const isSelected = originalSelectedSkillIdsSet.has(skill.skill_id);
            const isDisabled = isReadOnly;

            return (
              <div
                key={skill.skill_id}
                className={`border-2 rounded-md px-3 py-2 flex items-center justify-between transition-all duration-300 ease-in-out min-h-[44px] ${
                  isSelected
                    ? "bg-blue-100 border-blue-400 shadow-md"
                    : "border-gray-200 hover:border-blue-300 hover:shadow-md"
                } ${editable && !isDisabled ? "cursor-pointer" : "cursor-not-allowed opacity-60"}`}
                onClick={() => handleSkillClick(skill)}
              >
                <span className="font-medium text-gray-800 truncate">
                  {skill.name}
                </span>
                <Info
                  size={16}
                  className="flex-shrink-0 cursor-pointer text-gray-400 hover:text-gray-600 transition-colors"
                  onClick={(e) => handleInfoClick(skill, e)}
                />
              </div>
            );
          })}
        </div>
      ),
    };
  });

  return (
    <div className="h-full">
      {skillGroups.length === 0 ? (
        <div className="flex items-center justify-center h-full">
          <span className="text-gray-500">{t("skillPool.noSkills")}</span>
        </div>
      ) : (
        <Tabs
          tabPlacement="start"
          activeKey={activeTabKey}
          onChange={setActiveTabKey}
          items={tabItems}
          className="h-full skill-pool-tabs"
          style={{
            height: "100%",
          }}
          tabBarStyle={{
            minWidth: "80px",
            maxWidth: "100px",
            padding: "4px 0",
            margin: 0,
          }}
        />
      )}

      <SkillDetailModal
        skill={selectedSkill}
        open={isDetailModalOpen}
        onClose={() => {
          setIsDetailModalOpen(false);
          setSelectedSkill(null);
        }}
      />
    </div>
  );
}
