"use client";

import { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Row, Col, Flex, Tooltip, Badge, Divider } from "antd";
import CollaborativeAgent from "./agentConfig/CollaborativeAgent";
import ToolManagement from "./agentConfig/ToolManagement";

import { updateToolList } from "@/services/mcpService";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useToolList } from "@/hooks/agent/useToolList";
import McpConfigModal from "./agentConfig/McpConfigModal";

import { RefreshCw, Lightbulb, Plug } from "lucide-react";

interface AgentConfigCompProps {}

export default function AgentConfigComp({}: AgentConfigCompProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  // Get state from store
  const currentAgentId = useAgentConfigStore((state) => state.currentAgentId);

  const isCreatingMode = useAgentConfigStore((state) => state.isCreatingMode);

  const [isMcpModalOpen, setIsMcpModalOpen] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Use tool list hook for data management
  const { groupedTools, invalidate } = useToolList();

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
              <Badge count={2} color="blue" />
              <h2 className="text-lg font-medium">
                {t("businessLogic.config.title")}
              </h2>
            </Flex>
          </Col>
        </Row>

        <Divider style={{ margin: "10px 0" }} />

        <Row gutter={[12, 12]} className="mb-4">
          <CollaborativeAgent />
        </Row>

        <Row gutter={[12, 12]}>
          <Col xs={12}>
            <Flex justify="flex-start" align="center">
              <h4 className="text-md font-medium text-gray-700">
                {t("toolPool.title")}
              </h4>
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
                    color: "#374151",
                    border: "1px solid #e5e7eb",
                    borderRadius: "6px",
                    boxShadow:
                      "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)",
                    padding: "12px",
                    maxWidth: "800px",
                    minWidth: "700px",
                    width: "fit-content",
                  },
                }}
              >
                <Lightbulb className="ml-2 text-yellow-500" size={16} />
              </Tooltip>
            </Flex>
          </Col>
          <Col xs={12}>
            <Flex justify="flex-end" align="center">
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

        <Divider style={{ margin: "10px 0" }} />

        <Row className="flex:1 min-h-0">
          <Col xs={24} className="h-full">
            <ToolManagement
              toolGroups={groupedTools}
              isCreatingMode={isCreatingMode}
              currentAgentId={currentAgentId ?? undefined}
            />
          </Col>
        </Row>
      </Flex>

      <McpConfigModal
        visible={isMcpModalOpen}
        onCancel={() => setIsMcpModalOpen(false)}
      />
    </>
  );
}
