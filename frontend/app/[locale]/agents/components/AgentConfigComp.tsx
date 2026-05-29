"use client";

import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Row, Col, Flex, Tooltip, Badge, Divider } from "antd";
import CollaborativeAgent from "./agentConfig/CollaborativeAgent";
import ToolManagement from "./agentConfig/ToolManagement";
import SkillManagement from "./agentConfig/SkillManagement";
import SkillBuildModal from "./agentConfig/SkillBuildModal";

import { updateToolList } from "@/services/mcpService";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useToolList } from "@/hooks/agent/useToolList";
import { useSkillList } from "@/hooks/agent/useSkillList";
import { useExternalAgents } from "@/hooks/agent/useExternalAgents";
import McpConfigModal from "./agentConfig/McpConfigModal";
import A2AAgentDiscoveryModal from "./a2a/A2AAgentDiscoveryModal";

import { RefreshCw, Lightbulb, Plug, BlocksIcon, Globe } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

interface AgentConfigCompProps {}

export default function AgentConfigComp({}: AgentConfigCompProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  // Get state from store
  const currentAgentId = useAgentConfigStore((state) => state.currentAgentId);
  const isCreatingMode = useAgentConfigStore((state) => state.isCreatingMode);
  const isReadOnly = useAgentConfigStore((state) => state.isReadOnly());

  const [isMcpModalOpen, setIsMcpModalOpen] = useState(false);
  const [isSkillModalOpen, setIsSkillModalOpen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isRefreshingSkill, setIsRefreshingSkill] = useState(false);
  const [showA2ADiscovery, setShowA2ADiscovery] = useState(false);
  const showLegacyMcpConfig = false;

  // Use tool list hook for data management
  const { groupedTools, invalidate } = useToolList();
  const { groupedSkills, invalidate: invalidateSkills } = useSkillList();
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
    } catch (error) {
      message.error(t("toolManagement.message.refreshFailedRetry"));
    } finally {
      setIsRefreshing(false);
    }
  }, [invalidate]);

  const handleRefreshSkills = useCallback(async () => {
    setIsRefreshingSkill(true);
    try {
      invalidateSkills();
      message.success(t("skillManagement.message.refreshSuccess"));
    } catch (error) {
      message.error(t("skillManagement.message.refreshFailed"));
    } finally {
      setIsRefreshingSkill(false);
    }
  }, [invalidateSkills]);

  const handleSkillBuildSuccess = useCallback(() => {
    invalidateSkills();
  }, [invalidateSkills]);

  return (
    <>
      {/* Import handled by Ant Design Upload (no hidden input required) */}
      <Flex vertical className="h-full overflow-hidden">
        <Row>
          <Col>
            <Flex justify="flex-start" align="center" gap={8} style={{ marginBottom: "4px" }}>
              <Badge count={1} color="blue" />
              <h2 className="text-[16px] font-medium">{t("businessLogic.config.title")}</h2>
            </Flex>
          </Col>
        </Row>

        <Divider style={{ margin: "10px 0" }} />

        <Row gutter={[12, 12]} className="mb-2 flex-shrink-0">
          <Col xs={12}>
            <Flex justify="flex-start" align="center">
              <h4 className="text-md font-medium text-gray-700">{t("collaborativeAgent.title")}</h4>
            </Flex>
          </Col>
          <Col xs={12}>
            <Flex justify="flex-end" align="center">
              <Button
                type="text"
                size="small"
                icon={<Globe size={16} />}
                onClick={() => setShowA2ADiscovery(true)}
                className="text-green-500 hover:!text-green-600 hover:!bg-green-50"
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
      <Tabs defaultValue="tools" className="w-full flex-1 min-h-0 flex flex-col overflow-hidden">
        <TabsList className="grid w-full grid-cols-2 flex-shrink-0">
          <TabsTrigger value="tools">
            {t("toolPool.title")}
            <Tooltip
              title={<div style={{ whiteSpace: "pre-line" }}>{t("toolPool.tooltip.functionGuide")}</div>}
              color="#ffffff"
              styles={{
                root: {
                  backgroundColor: "#ffffff",
                  border: "1px solid #e5e7eb",
                  borderRadius: "6px",
                  boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)",
                  maxWidth: "800px",
                  minWidth: "700px",
                  width: "fit-content",
                },
              }}
            >
              <Lightbulb className="mx-2 text-yellow-500" size={16} />
            </Tooltip>
          </TabsTrigger>
          <TabsTrigger value="skills">{t("skillPool.title")}</TabsTrigger>
        </TabsList>

        <TabsContent value="tools" className="mt-4 flex-1 min-h-0 flex flex-col overflow-hidden">

          <Row gutter={[12, 12]} className="flex-shrink-0">
            <Col xs={24}>
              <Flex justify="flex-end" align="center" gap={8}>
                <Button
                  type="text"
                  size="small"
                  icon={<RefreshCw size={16} />}
                  onClick={handleRefreshTools}
                  loading={isRefreshing}
                  className="text-green-500 hover:!text-green-600 hover:!bg-green-50"
                  title={t("toolManagement.refresh.title")}
                >
                  {t("toolManagement.refresh.button.refresh")}
                </Button>
                <Button
                  type="text"
                  size="small"
                  icon={<Plug size={16} />}
                  onClick={() => setIsMcpModalOpen(true)}
                  className="text-blue-500 hover:!text-blue-600 hover:!bg-blue-50"
                  title={t("toolManagement.mcp.title")}
                >
                  {t("toolManagement.mcp.button")}
                </Button>
              </Flex>
            </Col>
          </Row>

          <Row className="flex-1 min-h-0 mt-4 overflow-y-auto">
            <Col xs={24} className="h-full">
              <ToolManagement
                toolGroups={groupedTools}
                isCreatingMode={isCreatingMode}
                currentAgentId={currentAgentId ?? undefined}
              />
            </Col>
          </Row>
        </TabsContent>

        <TabsContent value="skills" className="mt-4 flex-1 min-h-0 flex flex-col overflow-hidden">
          <Row gutter={[12, 12]} className="flex-shrink-0">
            <Col xs={24}>
              <Flex justify="flex-end" align="center" gap={8}>
                <Button
                  type="text"
                  size="small"
                  icon={<RefreshCw size={16} />}
                  onClick={handleRefreshSkills}
                  loading={isRefreshingSkill}
                  className="text-green-500 hover:!text-green-600 hover:!bg-green-50"
                  title={t("skillManagement.refresh.title")}
                >
                  {t("skillManagement.refresh.button")}
                </Button>
                <Button
                  type="text"
                  size="small"
                  icon={<BlocksIcon size={16} />}
                  onClick={() => setIsSkillModalOpen(true)}
                  className="text-blue-500 hover:!text-blue-600 hover:!bg-blue-50"
                  title={t("skillManagement.build.title")}
                >
                  {t("skillManagement.build.button")}
                </Button>
              </Flex>
            </Col>
          </Row>

          <Row className="flex-1 min-h-0 mt-4 overflow-y-auto">
            <Col xs={24} className="h-full">
              <SkillManagement
                skillGroups={groupedSkills}
                isCreatingMode={isCreatingMode}
                currentAgentId={currentAgentId ?? undefined}
                isReadOnly={isReadOnly}
              />
            </Col>
          </Row>
        </TabsContent>
      </Tabs>
      </Flex>

      <McpConfigModal visible={isMcpModalOpen} onCancel={() => setIsMcpModalOpen(false)} />

      <SkillBuildModal
        isOpen={isSkillModalOpen}
        onCancel={() => setIsSkillModalOpen(false)}
        onSuccess={handleSkillBuildSuccess}
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
