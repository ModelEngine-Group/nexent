"use client";

import { useTranslation } from "react-i18next";
import { App, Row, Col, Flex, Tooltip, Badge, Divider } from "antd";
import { FileInput, Plus, X } from "lucide-react";

import AgentList from "./agentManage/AgentList";

import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useAgentList } from "@/hooks/agent/useAgentList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import log from "@/lib/logger";
import { useState } from "react";
import {
  parseAgentImportFile,
  selectFile,
  type ImportAgentData,
} from "@/lib/agentImportUtils";
import AgentImportWizard from "@/components/agent/AgentImportWizard";


export default function AgentManageComp() {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  useAuthorizationContext();

  // Get state from store
  const isCreatingMode = useAgentConfigStore((state) => state.isCreatingMode);
  const enterCreateMode = useAgentConfigStore((state) => state.enterCreateMode);
  const reset = useAgentConfigStore((state) => state.reset);

  // Import wizard state
  const [importWizardVisible, setImportWizardVisible] = useState(false);
  const [importWizardData, setImportWizardData] =
    useState<ImportAgentData | null>(null);

  // Always resolve tenant from auth on the agent dev page (matches published_list; avoids stale/wrong tenant_id query params)
  const { agents: agentList, isLoading: loading, refetch } = useAgentList("");

  // Handle import agent for space view - open wizard instead of direct import
  const handleImportAgent = async () => {
    const file = await selectFile(".json");
    if (!file) return;

    const agentData = await parseAgentImportFile(file, {
      onParseError: (msgKey) => message.error(t(msgKey)),
      onValidationError: (msgKey) => message.error(t(msgKey)),
      onGenericError: (error) => {
        log.error("Failed to read import file:", error);
        message.error(t("businessLogic.config.error.agentImportFailed"));
      },
    });

    if (!agentData) return;

    setImportWizardData(agentData);
    setImportWizardVisible(true);
  };

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
              <h2 className="text-lg font-medium">
                {t("subAgentPool.management")}
              </h2>
            </Flex>
          </Col>
        </Row>

        <Divider style={{ margin: "10px 0" }} />

        <Row gutter={[12, 12]} className="mb-4">
          <Col xs={24} sm={12}>
            {isCreatingMode ? (
              <Tooltip title={t("subAgentPool.tooltip.exitCreateMode")}>
                <div
                  className="rounded-md p-3 cursor-pointer transition-all duration-200 bg-blue-100 border border-blue-200 shadow-sm"
                  onClick={reset}
                >
                  <Flex align="center" gap={12} className="text-blue-600">
                    <Flex
                      align="center"
                      justify="center"
                      className="w-8 h-8 rounded-full bg-blue-100 flex-shrink-0"
                    >
                      <X className="w-4 h-4" aria-hidden="true" />
                    </Flex>
                    <Flex vertical style={{ flex: 1 }}>
                      <div className="font-medium text-sm">
                        {t("subAgentPool.button.exitCreate")}
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">
                        {t("subAgentPool.description.exitCreate")}
                      </div>
                    </Flex>
                  </Flex>
                </div>
              </Tooltip>
            ) : (
              <Tooltip title={t("subAgentPool.tooltip.createNewAgent")}>
                <div
                  className="rounded-md p-3 cursor-pointer transition-all duration-200 bg-white hover:bg-blue-50 hover:shadow-sm"
                  onClick={enterCreateMode}
                >
                  <Flex align="center" gap={12} className="text-blue-600">
                    <Flex
                      align="center"
                      justify="center"
                      className="w-8 h-8 rounded-full bg-blue-100 flex-shrink-0"
                    >
                      <Plus className="w-4 h-4" aria-hidden="true" />
                    </Flex>
                    <Flex vertical style={{ flex: 1 }}>
                      <div className="font-medium text-sm">
                        {t("subAgentPool.button.create")}
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5">
                        {t("subAgentPool.description.createAgent")}
                      </div>
                    </Flex>
                  </Flex>
                </div>
              </Tooltip>
            )}
          </Col>

          <Col xs={24} sm={12}>
            <Tooltip title={t("subAgentPool.description.importAgent")}>
              <div
                className="rounded-md p-3 cursor-pointer transition-all duration-200 bg-white hover:bg-green-50 hover:shadow-sm"
                onClick={() => void handleImportAgent()}
              >
                <Flex align="center" gap={12} className="text-green-600">
                  <Flex
                    align="center"
                    justify="center"
                    className="w-8 h-8 rounded-full bg-green-100 flex-shrink-0"
                  >
                    <FileInput
                      className="w-4 h-4 text-green-600"
                      aria-hidden="true"
                    />
                  </Flex>
                  <Flex vertical style={{ flex: 1 }}>
                    <div className="font-medium text-sm">
                      {t("subAgentPool.button.import")}
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5">
                      {t("subAgentPool.description.importAgent")}
                    </div>
                  </Flex>
                </Flex>
              </div>
            </Tooltip>
          </Col>
        </Row>

        <div className="flex-1 min-h-0">
          <AgentList agentList={agentList} />
        </div>
      </Flex>

      {/* Import Wizard Modal */}
      <AgentImportWizard
        visible={importWizardVisible}
        onCancel={() => {
          setImportWizardVisible(false);
          setImportWizardData(null);
        }}
        initialData={importWizardData}
        onImportComplete={() => {
          setImportWizardVisible(false);
          setImportWizardData(null);
          refetch(); // Refresh the agent list
        }}
      />
    </>
  );
}
