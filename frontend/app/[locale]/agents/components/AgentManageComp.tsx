"use client";

import { useTranslation } from "react-i18next";
import { App, Row, Col, Flex, Tooltip, Badge, Divider } from "antd";
import { FileInput, Plus, X } from "lucide-react";

import { Agent } from "@/types/agentConfig";
import AgentList from "./agentManage/AgentList";
import { useSaveGuard } from "@/hooks/agent/useSaveGuard";
import { useCallback } from "react";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { importAgent } from "@/services/agentConfigService";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useAgentList } from "@/hooks/agent/useAgentList";
import { useAgentInfo } from "@/hooks/agent/useAgentInfo";
import log from "@/lib/logger";
import { useState, useEffect } from "react";
import { ImportAgentData } from "@/hooks/useAgentImport";
import AgentImportWizard from "@/components/agent/AgentImportWizard";
import { clearAgentNewMark } from "@/services/agentConfigService";
import { clearAgentAndSync } from "@/lib/agentNewUtils";

export default function AgentManageComp() {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  // Get state from store
  const currentAgentId = useAgentConfigStore((state) => state.currentAgentId);
  const hasUnsavedChanges = useAgentConfigStore(
    (state) => state.hasUnsavedChanges
  );
  const isCreatingMode = useAgentConfigStore((state) => state.isCreatingMode);
  const setCurrentAgent = useAgentConfigStore((state) => state.setCurrentAgent);
  const enterCreateMode = useAgentConfigStore((state) => state.enterCreateMode);
  const reset = useAgentConfigStore((state) => state.reset);

  // Unsaved changes guard
  const checkUnsavedChanges = useSaveGuard();

  // Handle unsaved changes check and agent switching
  const handleAgentSwitch = useCallback(
    async (agentDetail: any) => {
      const canSwitch = await checkUnsavedChanges.saveWithModal();
      if (canSwitch) {
        setCurrentAgent(agentDetail);
      }
    },
    [checkUnsavedChanges]
  );

  const editable = currentAgentId || isCreatingMode;

  // Shared agent list via React Query
  const { agents: agentList, isLoading: loading, refetch } = useAgentList();
  const queryClient = useQueryClient();

  // State for selected agent info loading
  const [selectedAgentId, setSelectedAgentId] = useState<number | null>(null);

  // Import wizard state
  const [importWizardVisible, setImportWizardVisible] = useState(false);
  const [importWizardData, setImportWizardData] =
    useState<ImportAgentData | null>(null);

  const {
    data: agentDetail,
    isLoading: agentInfoLoading,
    error: agentInfoError,
  } = useAgentInfo(selectedAgentId);

  const importAgentMutation = useMutation({
    mutationFn: (agentData: any) => importAgent(agentData),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agents"] }),
  });

  // Handle import agent for space view - open wizard instead of direct import
  const handleImportAgent = () => {
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = ".json";
    fileInput.onchange = async (event) => {
      const file = (event.target as HTMLInputElement).files?.[0];
      if (!file) return;

      if (!file.name.endsWith(".json")) {
        message.error(t("businessLogic.config.error.invalidFileType"));
        return;
      }

      try {
        // Read and parse file
        const fileContent = await file.text();
        let agentData: ImportAgentData;

        try {
          agentData = JSON.parse(fileContent);
        } catch (parseError) {
          message.error(t("businessLogic.config.error.invalidFileType"));
          return;
        }

        // Validate structure
        if (!agentData.agent_id || !agentData.agent_info) {
          message.error(t("businessLogic.config.error.invalidFileType"));
          return;
        }

        // Open wizard with parsed data
        setImportWizardData(agentData);
        setImportWizardVisible(true);
      } catch (error) {
        log.error("Failed to read import file:", error);
        message.error(t("businessLogic.config.error.agentImportFailed"));
      }
    };

    fileInput.click();
  };

  // Handle agent detail loading completion
  useEffect(() => {
    if (
      selectedAgentId &&
      agentDetail &&
      !agentInfoLoading &&
      !agentInfoError
    ) {
      const permissionFromList =
        agentList.find((a: Agent) => String(a.id) === String(selectedAgentId))
          ?.permission ?? null;
      // Handle agent switch with unsaved changes check
      handleAgentSwitch({
        ...agentDetail,
        permission: permissionFromList,
      });
      setSelectedAgentId(null);
    } else if (selectedAgentId && agentInfoError && !agentInfoLoading) {
      // Handle error
      log.error("Failed to load agent detail:", agentInfoError);
      message.error(t("agentConfig.agents.detailsLoadFailed"));
      setSelectedAgentId(null);
    }
  }, [
    selectedAgentId,
    agentDetail,
    agentInfoLoading,
    agentInfoError,
    handleAgentSwitch,
    message,
    t,
  ]);

  // Handle select agent
  const handleSelectAgent = async (agent: Agent) => {
    // If already selected, deselect it
    if (
      currentAgentId !== null &&
      String(currentAgentId) === String(agent.id)
    ) {
      const canDeselect = await checkUnsavedChanges.saveWithModal();
      if (canDeselect) {
        setCurrentAgent(null);
      }
      return;
    }

    // Clear NEW mark when agent is selected for editing (only if marked as new)
    if (agent.is_new === true) {
      try {
        const res = await clearAgentAndSync(agent.id, queryClient);
        if (!res?.success) {
          log.warn("Failed to clear NEW mark on select:", res);
        }
      } catch (err) {
        log.error("Failed to clear NEW mark on select:", err);
      }
    }

    // Set selected agent id to trigger the hook
    setSelectedAgentId(Number(agent.id));
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
                onClick={handleImportAgent}
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
          <AgentList
            agentList={agentList}
            currentAgentId={currentAgentId}
            hasUnsavedChanges={hasUnsavedChanges}
            onSelectAgent={handleSelectAgent}
            onAgentDeleted={(agentId) => {
              if (currentAgentId === agentId) {
                setCurrentAgent(null);
              }
            }}
          />
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
