"use client";

import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Row, Col, Flex, Tooltip, Badge } from "antd";
import { Wrench, RefreshCw, Plug, BlocksIcon } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { updateToolList } from "@/services/mcpService";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useToolList } from "@/hooks/agent/useToolList";
import { useSkillList } from "@/hooks/agent/useSkillList";
import ToolManagement from "./agentConfig/ToolManagement";
import SelectedSkillManagement from "./agentConfig/SelectedSkillManagement";
import McpConfigModal from "./agentConfig/McpConfigModal";
import SelectToolsDialog from "./agentConfig/tool/SelectToolsDialog";
import LabelManagementModal from "./agentConfig/tool/LabelManagementModal";
import SelectSkillsDialog from "./agentConfig/skill/SelectSkillsDialog";
import SkillTagManagementModal from "./agentConfig/skill/SkillTagManagementModal";

export default function AgentCapability() {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  const currentAgentId = useAgentConfigStore((state) => state.currentAgentId);
  const isCreatingMode = useAgentConfigStore((state) => state.isCreatingMode);
  const isReadOnly = useAgentConfigStore((state) => state.isReadOnly());
  const selectedTools = useAgentConfigStore((state) => state.editedAgent.tools);
  const selectedSkills = useAgentConfigStore((state) => state.editedAgent.skills);

  const [isMcpModalOpen, setIsMcpModalOpen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isRefreshingSkill, setIsRefreshingSkill] = useState(false);
  const [isToolSelectOpen, setIsToolSelectOpen] = useState(false);
  const [labelModalOpen, setLabelModalOpen] = useState(false);
  const [isSkillSelectOpen, setIsSkillSelectOpen] = useState(false);
  const [tagModalOpen, setTagModalOpen] = useState(false);

  const { invalidate, availableTools } = useToolList();
  const { invalidate: invalidateSkills } = useSkillList();

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

  return (
    <>
      <Tabs
        defaultValue="tools"
        className="w-full"
      >
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="tools">
            <span className="inline-flex items-center gap-1">
              {t("toolPool.title")}
              {selectedTools.length > 0 && (
                <Badge count={selectedTools.length} size="small" color="blue" />
              )}
            </span>
          </TabsTrigger>
          <TabsTrigger value="skills">
            <span className="inline-flex items-center gap-1">
              {t("skillPool.title")}
              {selectedSkills && selectedSkills.length > 0 && (
                <Badge count={selectedSkills.length} size="small" color="blue" />
              )}
            </span>
          </TabsTrigger>
        </TabsList>

        {/* Tools Tab */}
        <TabsContent value="tools" className="mt-3">
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
                  disabled={currentAgentId === null && !isCreatingMode}
                  className="!inline-flex h-7 !items-center !justify-center gap-1 border border-gray-200 bg-white text-xs leading-none hover:!border-gray-300 hover:!bg-gray-50"
                >
                  <span className="inline-flex items-center self-center leading-none">
                    {t("toolPool.selectTools")}
                  </span>
                </Button>
              </Flex>
            </Col>
          </Row>

          <ToolManagement
            isCreatingMode={isCreatingMode}
            currentAgentId={currentAgentId ?? undefined}
          />
        </TabsContent>

        {/* Skills Tab */}
        <TabsContent value="skills" className="mt-3">
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
                </div>
                <Button
                  size="small"
                  icon={<Wrench size={14} />}
                  onClick={() => setIsSkillSelectOpen(true)}
                  disabled={currentAgentId === null && !isCreatingMode}
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
            isCreatingMode={isCreatingMode}
            currentAgentId={currentAgentId ?? undefined}
            isReadOnly={isReadOnly}
          />
        </TabsContent>
      </Tabs>

      {/* Modals */}
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
        onEditSkill={() => {}}
        isCreatingMode={isCreatingMode}
        currentAgentId={currentAgentId ?? undefined}
        isReadOnly={isReadOnly}
      />

      <SkillTagManagementModal
        open={tagModalOpen}
        onClose={() => setTagModalOpen(false)}
      />
    </>
  );
}
