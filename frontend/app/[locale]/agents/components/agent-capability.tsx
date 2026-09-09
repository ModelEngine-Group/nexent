"use client";

import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Col, Flex, Row } from "antd";
import { BlocksIcon, Plug, RefreshCw, Wrench } from "lucide-react";

import { updateToolList } from "@/services/mcpService";
import { useAgentStore } from "@/stores/agentStore";
import { useAgentReadOnly } from "@/hooks/agent/useAgentReadOnly";
import { useToolList } from "@/hooks/agent/useToolList";
import { useSkillList } from "@/hooks/agent/useSkillList";
import type { Skill } from "@/types/agentConfig";
import type { MyEditableSkillItem } from "@/types/skillRepository";
import ToolManagement from "./agentConfig/ToolManagement";
import SkillBuildModal from "./agentConfig/SkillBuildModal";
import SelectedSkillManagement from "./agentConfig/SelectedSkillManagement";
import McpConfigModal from "./agentConfig/McpConfigModal";
import SelectToolsDialog from "./agentConfig/tool/SelectToolsDialog";
import LabelManagementModal from "./agentConfig/tool/LabelManagementModal";
import SelectSkillsDialog from "./agentConfig/skill/SelectSkillsDialog";
import SkillTagManagementModal from "./agentConfig/skill/SkillTagManagementModal";

export function AgentToolCapability() {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const currentAgentId = useAgentStore((state) => state.agentId);
  const isReadOnly = useAgentReadOnly();
  const [isMcpModalOpen, setIsMcpModalOpen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isToolSelectOpen, setIsToolSelectOpen] = useState(false);
  const [labelModalOpen, setLabelModalOpen] = useState(false);
  const { invalidate, availableTools } = useToolList();

  const handleRefreshTools = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const updateResult = await updateToolList();
      if (!updateResult.success) {
        message.warning(t("toolManagement.message.updateStatusFailed"));
      }
      invalidate();
      message.success(t("toolManagement.message.refreshSuccess"));
    } catch {
      message.error(t("toolManagement.message.refreshFailedRetry"));
    } finally {
      setIsRefreshing(false);
    }
  }, [invalidate, message, t]);

  return (
    <>
      <Row gutter={[12, 12]} className="mb-3">
        <Col xs={24}>
          <Flex justify="space-between" align="center">
            <div className="flex items-center gap-4 text-sm">
              <Button
                type="text"
                size="small"
                icon={<RefreshCw size={16} />}
                onClick={handleRefreshTools}
                loading={isRefreshing}
                className="!text-emerald-600 hover:!text-emerald-700 hover:!bg-emerald-50"
              >
                {t("toolManagement.refresh.button.refresh")}
              </Button>
              <Button
                type="text"
                size="small"
                icon={<Plug size={16} />}
                onClick={() => setIsMcpModalOpen(true)}
                className="!text-blue-600 hover:!text-blue-700 hover:!bg-blue-50"
              >
                {t("toolManagement.mcp.button")}
              </Button>
            </div>
            <Button
              size="small"
              icon={<Wrench size={14} />}
              onClick={() => setIsToolSelectOpen(true)}
              disabled={currentAgentId === null || isReadOnly}
              className="!inline-flex h-7 !items-center !justify-center gap-1 border border-gray-200 bg-white text-xs leading-none hover:!border-gray-300 hover:!bg-gray-50"
            >
              <span className="inline-flex items-center self-center leading-none">
                {t("toolPool.selectTools")}
              </span>
            </Button>
          </Flex>
        </Col>
      </Row>
      <ToolManagement currentAgentId={currentAgentId ?? undefined} />
      <McpConfigModal
        visible={isMcpModalOpen}
        onCancel={() => setIsMcpModalOpen(false)}
      />
      <SelectToolsDialog
        open={isToolSelectOpen}
        onClose={() => setIsToolSelectOpen(false)}
        onOpenManageLabels={() => setLabelModalOpen(true)}
        currentAgentId={currentAgentId ?? undefined}
      />
      <LabelManagementModal
        open={labelModalOpen}
        onClose={() => setLabelModalOpen(false)}
        availableTools={availableTools}
      />
    </>
  );
}

export function AgentSkillCapability() {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const currentAgentId = useAgentStore((state) => state.agentId);
  const isReadOnly = useAgentReadOnly();
  const [isSkillModalOpen, setIsSkillModalOpen] = useState(false);
  const [isRefreshingSkill, setIsRefreshingSkill] = useState(false);
  const [isSkillSelectOpen, setIsSkillSelectOpen] = useState(false);
  const [tagModalOpen, setTagModalOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<MyEditableSkillItem | null>(
    null
  );
  const { invalidate: invalidateSkills } = useSkillList();

  const handleRefreshSkills = useCallback(async () => {
    setIsRefreshingSkill(true);
    try {
      invalidateSkills();
      message.success(t("skillManagement.message.refreshSuccess"));
    } catch {
      message.error(t("skillManagement.message.refreshFailed"));
    } finally {
      setIsRefreshingSkill(false);
    }
  }, [invalidateSkills, message, t]);

  const handleSkillBuildSuccess = useCallback(
    () => invalidateSkills(),
    [invalidateSkills]
  );
  const handleOpenSkillEditor = useCallback((skill: Skill) => {
    setEditingSkill({
      skill_id: Number(skill.skill_id),
      name: skill.name,
      description: skill.description,
      source: skill.source,
      tags: skill.tags || [],
      group_ids: skill.group_ids || [],
      ingroup_permission: skill.ingroup_permission || "READ_ONLY",
      created_by: skill.created_by,
      updated_by: skill.updated_by,
      create_time: skill.create_time,
      update_time: skill.update_time,
      permission: skill.permission,
      repository_info: [],
    });
    setIsSkillModalOpen(true);
  }, []);
  const handleCloseSkillModal = useCallback(() => {
    setIsSkillModalOpen(false);
    setEditingSkill(null);
  }, []);

  return (
    <>
      <Row gutter={[12, 12]} className="mb-3">
        <Col xs={24}>
          <Flex justify="space-between" align="center">
            <div className="flex items-center gap-4 text-sm">
              <Button
                type="text"
                size="small"
                icon={<RefreshCw size={16} />}
                onClick={handleRefreshSkills}
                loading={isRefreshingSkill}
                className="!text-emerald-600 hover:!text-emerald-700 hover:!bg-emerald-50"
              >
                {t("skillManagement.refresh.button")}
              </Button>
              <Button
                type="text"
                size="small"
                icon={<BlocksIcon size={16} />}
                onClick={() => {
                  setEditingSkill(null);
                  setIsSkillModalOpen(true);
                }}
                className="!text-blue-600 hover:!text-blue-700 hover:!bg-blue-50"
                title={t("skillManagement.build.title")}
              >
                {t("skillManagement.build.button")}
              </Button>
            </div>
            <Button
              size="small"
              icon={<Wrench size={14} />}
              onClick={() => setIsSkillSelectOpen(true)}
              disabled={currentAgentId === null || isReadOnly}
              className="!inline-flex h-7 !items-center !justify-center gap-1 border border-gray-200 bg-white text-xs leading-none hover:!border-gray-300 hover:!bg-gray-50"
            >
              <span className="inline-flex items-center self-center leading-none">
                {t("skillPool.selectSkills")}
              </span>
            </Button>
          </Flex>
        </Col>
      </Row>
      <SelectedSkillManagement
        currentAgentId={currentAgentId ?? undefined}
        isReadOnly={isReadOnly}
        onEditSkill={handleOpenSkillEditor}
      />
      <SelectSkillsDialog
        open={isSkillSelectOpen}
        onClose={() => setIsSkillSelectOpen(false)}
        onOpenManageTags={() => setTagModalOpen(true)}
        onEditSkill={handleOpenSkillEditor}
        currentAgentId={currentAgentId ?? undefined}
        isReadOnly={isReadOnly}
      />
      <SkillTagManagementModal
        open={tagModalOpen}
        onClose={() => setTagModalOpen(false)}
      />
      <SkillBuildModal
        isOpen={isSkillModalOpen}
        onCancel={handleCloseSkillModal}
        onSuccess={handleSkillBuildSuccess}
        editingSkill={editingSkill}
        zIndex={1100}
      />
    </>
  );
}
