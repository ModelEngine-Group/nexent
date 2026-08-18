"use client";

import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Row, Col, Flex, Tooltip, Badge, Divider } from "antd";
import CollaborativeAgent from "./agentConfig/CollaborativeAgent";
import ToolManagement from "./agentConfig/ToolManagement";
import SkillBuildModal from "./agentConfig/SkillBuildModal";
import SelectedSkillManagement from "./agentConfig/SelectedSkillManagement";
import SelectToolsDialog from "./agentConfig/tool/SelectToolsDialog";
import LabelManagementModal from "./agentConfig/tool/LabelManagementModal";
import SelectSkillsDialog from "./agentConfig/skill/SelectSkillsDialog";
import SkillTagManagementModal from "./agentConfig/skill/SkillTagManagementModal";

import { updateToolList } from "@/services/mcpService";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useToolList } from "@/hooks/agent/useToolList";
import { useSkillList } from "@/hooks/agent/useSkillList";
import { useExternalAgents } from "@/hooks/agent/useExternalAgents";
import type { Skill } from "@/types/agentConfig";
import type { MyEditableSkillItem } from "@/types/skillRepository";
import McpConfigModal from "./agentConfig/McpConfigModal";
import A2AAgentDiscoveryModal from "./a2a/A2AAgentDiscoveryModal";

import {
  Wrench,
  RefreshCw,
  Lightbulb,
  Plug,
  BlocksIcon,
  Globe,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAgentReadOnly } from "@/hooks/agent/useAgentReadOnly";

export default function AgentConfigComp() {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  // Get state from store
  const currentAgentId = useAgentConfigStore((state) => state.currentAgentId);
  const isCreatingMode = useAgentConfigStore((state) => state.isCreatingMode);
  const isReadOnly = useAgentReadOnly();
  const selectedTools = useAgentConfigStore((state) => state.editedAgent.tools);
  const selectedSkills = useAgentConfigStore(
    (state) => state.editedAgent.skills
  );

  const [isMcpModalOpen, setIsMcpModalOpen] = useState(false);
  const [isSkillModalOpen, setIsSkillModalOpen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isRefreshingSkill, setIsRefreshingSkill] = useState(false);
  const [showA2ADiscovery, setShowA2ADiscovery] = useState(false);
  const [isToolSelectOpen, setIsToolSelectOpen] = useState(false);
  const [labelModalOpen, setLabelModalOpen] = useState(false);
  const [isSkillSelectOpen, setIsSkillSelectOpen] = useState(false);
  const [tagModalOpen, setTagModalOpen] = useState(false);
  const [editingSkill, setEditingSkill] = useState<MyEditableSkillItem | null>(
    null
  );

  // Use tool list hook for data management
  const { invalidate, availableTools } = useToolList();
  const { invalidate: invalidateSkills } = useSkillList();
  const { invalidate: invalidateExternalAgents } = useExternalAgents();

  const handleRefreshTools = useCallback(async () => {
    setIsRefreshing(true);
    try {
      // Step 1: Update backend tool status, rescan MCP and local tools
      const updateResult = await updateToolList();
      if (!updateResult.success) {
        message.warning(t("toolManagement.message.updateStatusFailed"));
      }

      // Step 2: Invalidate and refresh tool list cache
      invalidate();
      message.success(t("toolManagement.message.refreshSuccess"));
    } catch {
      message.error(t("toolManagement.message.refreshFailedRetry"));
    } finally {
      setIsRefreshing(false);
    }
  }, [invalidate, message, t]);

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

  const handleSkillBuildSuccess = useCallback(() => {
    invalidateSkills();
  }, [invalidateSkills]);

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
      {/* Import handled by Ant Design Upload (no hidden input required) */}
      <Flex vertical className="h-full overflow-hidden">
        <Row>
          <Col>
            <Flex
              justify="flex-start"
              align="center"
              gap={8}
              style={{ marginBottom: "4px" }}
            >
              <Badge count={1} color="blue" />
              <h2 className="text-[16px] font-medium">
                {t("businessLogic.config.title")}
              </h2>
            </Flex>
          </Col>
        </Row>

        <Divider style={{ margin: "10px 0" }} />

        <Row gutter={[12, 12]} className="mb-2 flex-shrink-0">
          <Col xs={12}>
            <Flex justify="flex-start" align="center">
              <h4 className="text-md font-medium text-gray-700">
                {t("collaborativeAgent.title")}
              </h4>
            </Flex>
          </Col>
          <Col xs={12}>
            <Flex justify="flex-end" align="center">
              <Button
                type="text"
                size="small"
                icon={<Globe size={16} />}
                onClick={() => setShowA2ADiscovery(true)}
                disabled={isReadOnly}
                className="!text-green-600 hover:!bg-green-50 hover:!text-green-700"
                title={t("toolManagement.refresh.title")}
              >
                {t("collaborativeAgent.addExternal")}
              </Button>
            </Flex>
          </Col>
        </Row>

        <Row className="mb-4 flex-shrink-0">
          <Col xs={24} className="h-full">
            <CollaborativeAgent />
          </Col>
        </Row>

        {/* Tool/Skill Tabs */}
        <Tabs
          defaultValue="tools"
          className="w-full flex-1 min-h-0 flex flex-col overflow-hidden"
        >
          <TabsList className="grid w-full grid-cols-2 flex-shrink-0">
            <TabsTrigger value="tools">
              <span className="inline-flex items-center gap-1">
                {t("toolPool.title")}
                {selectedTools.length > 0 && (
                  <Badge
                    count={selectedTools.length}
                    size="small"
                    color="blue"
                  />
                )}
              </span>
              <Tooltip
                title={
                  <div style={{ whiteSpace: "pre-line" }}>
                    {t("toolPool.tooltip.functionGuide")}
                  </div>
                }
                color="#ffffff"
                styles={{
                  root: {
                    backgroundColor: "#ffffff",
                    border: "1px solid #e5e7eb",
                    borderRadius: "6px",
                    boxShadow:
                      "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)",
                    maxWidth: "800px",
                    minWidth: "700px",
                    width: "fit-content",
                  },
                }}
              >
                <Lightbulb className="mx-2 text-yellow-500" size={16} />
              </Tooltip>
            </TabsTrigger>
            <TabsTrigger value="skills">
              <span className="inline-flex items-center gap-1">
                {t("skillPool.title")}
                {selectedSkills && selectedSkills.length > 0 && (
                  <Badge
                    count={selectedSkills.length}
                    size="small"
                    color="blue"
                  />
                )}
              </span>
            </TabsTrigger>
          </TabsList>

          <TabsContent
            value="tools"
            className="mt-4 flex-1 min-h-0 flex flex-col overflow-hidden"
          >
            <Row gutter={[12, 12]} className="flex-shrink-0">
              <Col xs={24}>
                <Flex justify="space-between" align="center">
                  {/* Left: action text links (mirrors demo's Refresh / MCP Config pattern) */}
                  <div className="flex items-center gap-4 text-sm">
                    <Button
                      type="text"
                      size="small"
                      icon={<RefreshCw size={16} />}
                      onClick={handleRefreshTools}
                      loading={isRefreshing}
                      disabled={isReadOnly}
                      className="!text-emerald-600 hover:!text-emerald-700 hover:!bg-emerald-50"
                    >
                      {t("toolManagement.refresh.button.refresh")}
                    </Button>
                    <Button
                      type="text"
                      size="small"
                      icon={<Plug size={16} />}
                      onClick={() => setIsMcpModalOpen(true)}
                      disabled={isReadOnly}
                      className="!text-blue-600 hover:!text-blue-700 hover:!bg-blue-50"
                    >
                      {t("toolManagement.mcp.button")}
                    </Button>
                  </div>
                  {/* Right: Select Tools button (mirrors demo) */}
                  <div className="flex items-center gap-2">
                    <Button
                      size="small"
                      icon={<Wrench size={14} />}
                      onClick={() => setIsToolSelectOpen(true)}
                      disabled={
                        isReadOnly ||
                        (currentAgentId === null && !isCreatingMode)
                      }
                      className="!inline-flex h-7 !items-center !justify-center gap-1 border border-gray-200 bg-white text-xs leading-none hover:!border-gray-300 hover:!bg-gray-50"
                    >
                      <span className="inline-flex items-center self-center leading-none">
                        {t("toolPool.selectTools")}
                      </span>
                    </Button>
                  </div>
                </Flex>
              </Col>
            </Row>

            <Row className="flex-1 min-h-0 mt-4 overflow-y-auto">
              <Col xs={24} className="h-full">
                <ToolManagement
                  isCreatingMode={isCreatingMode}
                  currentAgentId={currentAgentId ?? undefined}
                  isReadOnly={isReadOnly}
                />
              </Col>
            </Row>
          </TabsContent>

          <TabsContent
            value="skills"
            className="mt-4 flex-1 min-h-0 flex flex-col overflow-hidden"
          >
            <Row gutter={[12, 12]} className="flex-shrink-0">
              <Col xs={24}>
                <Flex justify="space-between" align="center">
                  <div className="flex items-center gap-4 text-sm">
                    <Button
                      type="text"
                      size="small"
                      icon={<RefreshCw size={16} />}
                      onClick={handleRefreshSkills}
                      loading={isRefreshingSkill}
                      disabled={isReadOnly}
                      className="!text-emerald-600 hover:!text-emerald-700 hover:!bg-emerald-50"
                      title={t("skillManagement.refresh.title")}
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
                      disabled={isReadOnly}
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
                    disabled={
                      isReadOnly || (currentAgentId === null && !isCreatingMode)
                    }
                    className="!inline-flex h-7 !items-center !justify-center gap-1 border border-gray-200 bg-white text-xs leading-none hover:!border-gray-300 hover:!bg-gray-50"
                  >
                    <span className="inline-flex items-center self-center leading-none">
                      {t("skillPool.selectSkills")}
                    </span>
                  </Button>
                </Flex>
              </Col>
            </Row>

            <Row className="flex-1 min-h-0 mt-4 overflow-y-auto">
              <Col xs={24} className="h-full">
                <SelectedSkillManagement
                  isCreatingMode={isCreatingMode}
                  currentAgentId={currentAgentId ?? undefined}
                  isReadOnly={isReadOnly}
                  onEditSkill={handleOpenSkillEditor}
                />
              </Col>
            </Row>
          </TabsContent>
        </Tabs>
      </Flex>

      <McpConfigModal
        visible={isMcpModalOpen}
        onCancel={() => setIsMcpModalOpen(false)}
      />

      <SelectToolsDialog
        open={isToolSelectOpen}
        onClose={() => setIsToolSelectOpen(false)}
        onOpenManageLabels={() => setLabelModalOpen(true)}
        isCreatingMode={isCreatingMode}
        currentAgentId={currentAgentId ?? undefined}
        isReadOnly={isReadOnly}
      />

      <LabelManagementModal
        open={labelModalOpen}
        onClose={() => setLabelModalOpen(false)}
        availableTools={availableTools}
      />

      <SelectSkillsDialog
        open={isSkillSelectOpen}
        onClose={() => setIsSkillSelectOpen(false)}
        onOpenManageTags={() => setTagModalOpen(true)}
        onEditSkill={(skill) => {
          handleOpenSkillEditor(skill);
        }}
        isCreatingMode={isCreatingMode}
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

      {/* A2A Discovery Modal */}
      <A2AAgentDiscoveryModal
        open={showA2ADiscovery}
        onClose={() => setShowA2ADiscovery(false)}
        onDiscoverSuccess={invalidateExternalAgents}
      />
    </>
  );
}
