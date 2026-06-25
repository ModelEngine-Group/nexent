"use client";

import { useTranslation } from "react-i18next";
import { App, Flex, Button, Badge, Dropdown, Tooltip, Col, Row, Modal, Spin, Tag, theme } from "antd";
import { useMutation } from "@tanstack/react-query";
import { Plus, FileInput, Settings, ChevronDown, Bot, Copy, Network, FileOutput, Trash2, Globe, GitBranch, History } from "lucide-react";
import { ExclamationCircleOutlined } from "@ant-design/icons";
import { useState } from "react";
import { StaticScrollArea } from "@/components/ui/scrollArea";
import AgentCallRelationshipModal from "@/components/agent/AgentCallRelationshipModal";
import A2AServerSettingsPanel from "./a2a/A2AServerSettingsPanel";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { a2aClientService } from "@/services/a2aService";
import { useQuery } from "@tanstack/react-query";
import {
  searchAgentInfo,
  updateAgentInfo,
  deleteAgent,
  exportAgent,
  updateToolConfig,
  clearAgentNewMark,
} from "@/services/agentConfigService";

import { Agent } from "@/types/agentConfig";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useSaveGuard } from "@/hooks/agent/useSaveGuard";
import { useQueryClient } from "@tanstack/react-query";
import AgentImportWizard from "@/components/agent/AgentImportWizard";
import { ImportAgentData } from "@/lib/agentImportUtils";
import log from "@/lib/logger";
import { useAgentList } from "@/hooks/agent/useAgentList";
import { useAgentVersionList } from "@/hooks/agent/useAgentVersionList";
import { useAgentVersionDetail } from "@/hooks/agent/useAgentVersionDetail";
import { useAgentInfo } from "@/hooks/agent/useAgentInfo";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";

interface AgentSelectorHeaderProps {
  onOpenVersionManage: () => void;
  isShowVersionManagePanel?: boolean;
  onCloseVersionManagePanel?: () => void;
}

export default function AgentSelectorHeader({
  onOpenVersionManage,
  isShowVersionManagePanel = false,
  onCloseVersionManagePanel,
}: AgentSelectorHeaderProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const checkUnsavedChanges = useSaveGuard();
  const confirm = useConfirmModal();
  const { token } = theme?.useToken?.() || {};
  const { user } = useAuthorizationContext();

  // Fetch agent list internally
  const { agents } = useAgentList(user?.tenantId ?? null);

  // Store state
  const currentAgentId = useAgentConfigStore((state) => state.currentAgentId);
  const setCurrentAgent = useAgentConfigStore((state) => state.setCurrentAgent);
  const isCreatingMode = useAgentConfigStore((state) => state.isCreatingMode);
  const enterCreateMode = useAgentConfigStore((state) => state.enterCreateMode);
  const reset = useAgentConfigStore((state) => state.reset);
  const hasUnsavedChanges = useAgentConfigStore((state) => state.hasUnsavedChanges);

  const { agentInfo } = useAgentInfo(currentAgentId);
  const { agentVersionList, total } = useAgentVersionList(currentAgentId);
  const { agentVersionDetail } = useAgentVersionDetail(currentAgentId, agentInfo?.current_version_no);

  // Call relationship modal state
  const [callRelationshipModalVisible, setCallRelationshipModalVisible] = useState(false);
  const [selectedAgentForRelationship, setSelectedAgentForRelationship] = useState<Agent | null>(null);

  // A2A settings modal state
  const [showA2ASettings, setShowA2ASettings] = useState(false);
  const [selectedAgentForA2A, setSelectedAgentForA2A] = useState<Agent | null>(null);

  // Dropdown open state
  const [dropdownOpen, setDropdownOpen] = useState(false);

  // Mutations
  const updateAgentMutation = useMutation({
    mutationFn: (payload: any) => updateAgentInfo(payload),
  });

  const deleteAgentMutation = useMutation({
    mutationFn: (agentId: number) => deleteAgent(agentId),
  });

  // Fetch A2A Server Settings when modal opens
  const { data: a2aSettingsData, isLoading: isLoadingA2ASettings } = useQuery({
    queryKey: ["a2aServerSettings", selectedAgentForA2A?.id],
    queryFn: () => a2aClientService.getServerSettings(Number(selectedAgentForA2A!.id)),
    enabled: showA2ASettings && !!selectedAgentForA2A,
  });

  // Construct a2aAgentCard from supported_interfaces
  const constructedA2AAgentCard = (() => {
    const data = a2aSettingsData?.data;
    if (!data?.supported_interfaces) return undefined;

    const interfaces = data.supported_interfaces;
    const endpointId = data.endpoint_id;
    const restEndpoints = interfaces.filter(
      (iface: any) => iface.protocolBinding.toLowerCase() === "http+json" || iface.protocolBinding.toLowerCase() === "httprest"
    );
    const jsonrpcEndpoints = interfaces.filter(
      (iface: any) =>
        iface.protocolBinding.toLowerCase() === "http-json-rpc" ||
        iface.protocolBinding.toLowerCase() === "jsonrpc" ||
        iface.protocolBinding.toLowerCase() === "httpjsonrpc"
    );

    return {
      endpoint_id: endpointId,
      name: data.name || "",
      description: data.description,
      version: data.version,
      streaming: data.streaming,
      agent_card_url: `/nb/a2a/${endpointId}/.well-known/agent-card.json`,
      rest_endpoints: {
        message_send: `${restEndpoints[0]?.url}/message:send`,
        message_stream: `${restEndpoints[0]?.url}/message:stream`,
        tasks_get: `${restEndpoints[0]?.url}/tasks/{task_id}`,
      },
      jsonrpc_url: jsonrpcEndpoints[0]?.url || "",
      jsonrpc_methods: ["SendMessage", "SendStreamingMessage", "GetTask"],
    };
  })();

  // Import wizard state
  const [importWizardVisible, setImportWizardVisible] = useState(false);
  const [importWizardData, setImportWizardData] = useState<ImportAgentData | null>(null);

  // Get current selected agent
  const currentAgent = agents.find(
    (agent: Agent) => currentAgentId !== null && String(agent.id) === String(currentAgentId)
  );

  // Handle import agent
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
        const fileContent = await file.text();
        let agentData: ImportAgentData;

        try {
          agentData = JSON.parse(fileContent);
        } catch (parseError) {
          message.error(t("businessLogic.config.error.invalidFileType"));
          return;
        }

        if (!agentData.agent_id || !agentData.agent_info) {
          message.error(t("businessLogic.config.error.invalidFileType"));
          return;
        }

        setImportWizardData(agentData);
        setImportWizardVisible(true);
      } catch (error) {
        log.error("Failed to read import file:", error);
        message.error(t("businessLogic.config.error.agentImportFailed"));
      }
    };

    fileInput.click();
  };

  // Handle view call relationship
  const handleViewCallRelationship = (agent: Agent) => {
    setSelectedAgentForRelationship(agent);
    setCallRelationshipModalVisible(true);
    setDropdownOpen(false);
  };

  const handleCloseCallRelationshipModal = () => {
    setCallRelationshipModalVisible(false);
    setSelectedAgentForRelationship(null);
  };

  // Handle view A2A agent settings
  const handleViewA2AAgentSettings = (agent: Agent) => {
    setSelectedAgentForA2A(agent);
    setShowA2ASettings(true);
    setDropdownOpen(false);
  };

  // Handle export agent
  const handleExportAgent = async (agent: Agent) => {
    try {
      const result = await exportAgent(Number(agent.id));
      if (result.success && result.data) {
        const blob = new Blob([JSON.stringify(result.data, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${agent.name || "agent"}.json`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        message.success(t("businessLogic.config.message.agentExportSuccess"));
      } else {
        message.error(
          result.message || t("businessLogic.config.error.agentImportFailed")
        );
      }
    } catch (error) {
      message.error(t("businessLogic.config.error.agentExportFailed"));
    }
  };

  // Handle copy agent
  const handleCopyAgent = async (agent: Agent) => {
    try {
      const detailResult = await searchAgentInfo(Number(agent.id));
      if (!detailResult.success || !detailResult.data) {
        message.error(detailResult.message);
        return;
      }
      const detail = detailResult.data;

      const copyName = `${detail.name || "agent"}_copy`;
      const copyDisplayName = `${
        detail.display_name || t("agentConfig.agents.defaultDisplayName")
      }${t("agent.copySuffix")}`;

      const tools = Array.isArray(detail.tools) ? detail.tools : [];
      const unavailableTools = tools.filter(
        (tool: any) => tool && tool.is_available === false
      );
      const unavailableToolNames = unavailableTools
        .map(
          (tool: any) =>
            tool?.display_name || tool?.name || tool?.tool_name || ""
        )
        .filter((name: string) => Boolean(name));

      const enabledToolIds = tools
        .filter((tool: any) => tool && tool.is_available !== false)
        .map((tool: any) => Number(tool.id))
        .filter((id: number) => Number.isFinite(id));

      const subAgentIds = (
        Array.isArray(detail.sub_agent_id_list) ? detail.sub_agent_id_list : []
      )
        .map((id: any) => Number(id))
        .filter((id: number) => Number.isFinite(id));

      const createResult = await updateAgentMutation.mutateAsync({
        agent_id: undefined, // create
        name: copyName,
        display_name: copyDisplayName,
        description: detail.description,
        author: detail.author,
        model_name: detail.model,
        model_id: detail.model_id ?? undefined,
        max_steps: detail.max_step,
        provide_run_summary: detail.provide_run_summary,
        enabled: detail.enabled,
        business_description: detail.business_description,
        duty_prompt: detail.duty_prompt,
        constraint_prompt: detail.constraint_prompt,
        few_shots_prompt: detail.few_shots_prompt,
        business_logic_model_name: detail.business_logic_model_name ?? undefined,
        business_logic_model_id: detail.business_logic_model_id ?? undefined,
        enabled_tool_ids: enabledToolIds,
        related_agent_ids: subAgentIds,
      });

      if (!createResult.success || !createResult.data?.agent_id) {
        message.error(
          createResult.message || t("agentConfig.agents.copyFailed")
        );
        return;
      }
      const newAgentId = Number(createResult.data.agent_id);

      // Copy tool configuration
      for (const tool of tools) {
        if (!tool || tool.is_available === false) continue;
        const params =
          tool.initParams?.reduce((acc: Record<string, any>, param: any) => {
            acc[param.name] = param.value;
            return acc;
          }, {}) || {};
        try {
          await updateToolConfig(Number(tool.id), newAgentId, params, true);
        } catch (error) {
          log.error("Failed to copy tool configuration:", error);
          message.error(t("agentConfig.agents.copyFailed"));
          return;
        }
      }

      // Refresh agent list
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      message.success(t("agentConfig.agents.copySuccess"));

      if (unavailableTools.length > 0) {
        const names =
          unavailableToolNames.join(", ") ||
          unavailableTools
            .map((tool: any) => Number(tool?.id))
            .filter((id: number) => !Number.isNaN(id))
            .join(", ");
        message.warning(
          t("agentConfig.agents.copyUnavailableTools", {
            count: unavailableTools.length,
            names,
          })
        );
      }
    } catch (error) {
      log.error("Failed to copy agent:", error);
      message.error(t("agentConfig.agents.copyFailed"));
    }
  };

  // Handle copy with confirmation
  const handleCopyAgentWithConfirm = (agent: Agent) => {
    confirm.confirm({
      title: t("agentConfig.agents.copyConfirmTitle"),
      content: t("agentConfig.agents.copyConfirmContent", {
        name: agent?.display_name || agent?.name || "",
      }),
      onOk: () => handleCopyAgent(agent),
    });
  };

  // Handle delete agent
  const handleDeleteAgent = async (agent: Agent) => {
    deleteAgentMutation.mutate(Number(agent.id), {
      onSuccess: () => {
        message.success(
          t("businessLogic.config.error.agentDeleteSuccess", {
            name: agent.display_name || agent.name || "",
          })
        );

        // Clear current agent if this was the selected agent
        if (
          currentAgentId !== null &&
          String(currentAgentId) === String(agent.id)
        ) {
          setCurrentAgent(null);
        }

        // Refresh agent list
        queryClient.invalidateQueries({ queryKey: ["agents"] });
      },
      onError: () => {
        message.error(t("businessLogic.config.error.agentDeleteFailed"));
      },
    });
  };

  // Handle delete with confirmation
  const handleDeleteAgentWithConfirm = (agent: Agent) => {
    confirm.confirm({
      title: t("businessLogic.config.modal.deleteTitle"),
      content: t("businessLogic.config.modal.deleteContent", {
        name: agent.display_name || agent.name || "",
      }),
      onOk: () => handleDeleteAgent(agent),
    });
  };

  // Handle select agent from dropdown
  const handleSelectAgent = async (agentId: number | null) => {
    if (agentId === null) return;

    const agent = agents.find((a: Agent) => String(a.id) === String(agentId));
    if (!agent) return;

    // Clear NEW mark when agent is selected for editing
    if (agent.is_new === true) {
      try {
        const res = await clearAgentNewMark(agent.id);
        if (!res?.success) {
          log.warn("Failed to clear NEW mark on select:", res);
          queryClient.invalidateQueries({ queryKey: ["agents"] });
        }
      } catch (err) {
        log.error("Failed to clear NEW mark on select:", err);
      }
    }

    // Guard unsaved changes
    if (currentAgentId !== null || isCreatingMode) {
      const canSwitch = await checkUnsavedChanges.saveWithModal();
      if (!canSwitch) return;
    }

    // Load and set agent
    try {
      const result = await searchAgentInfo(Number(agent.id));
      if (result.success && result.data) {
        setCurrentAgent(result.data);
      } else {
        message.error(result.message || t("agentConfig.agents.detailsLoadFailed"));
      }
    } catch (error) {
      log.error("Failed to load agent detail:", error);
      message.error(t("agentConfig.agents.detailsLoadFailed"));
    }
  };

  // Dropdown menu items (only agents)
  const agentMenuItems = agents.flatMap((agent: Agent, index: number) => {
    const isAvailable = agent.is_available !== false;
    const displayName = agent.display_name || "";
    const name = agent.name || "";

    const agentItem = {
      key: `agent-${agent.id}`,
      label: (
        <div className="py-2">
          <Flex vertical gap={8}>
            {/* Row 1: Name + Status */}
          <div className={`font-medium text-base truncate min-w-0 ${!isAvailable ? "text-gray-500" : ""}`}>
            <div className="flex justify-between" style={{ gap: 6 }}>
              <Flex gap={4} align="center">
                {!isAvailable && (
                  <Tooltip
                    title={(() => {
                      const reasons = agent.unavailable_reasons || [];
                      if (reasons.includes('agent_not_found')) {
                        return t('subAgentPool.tooltip.unavailableAgent');
                      } else if (reasons.includes('tool_unavailable')) {
                        return t('toolPool.tooltip.unavailableTool');
                      } else if (reasons.includes('duplicate_name')) {
                        return t('agent.error.nameExists', { name });
                      } else if (reasons.includes('duplicate_display_name')) {
                        return t('agent.error.displayNameExists', { displayName });
                      } else if (reasons.includes('model_unavailable')) {
                        return t('agent.error.modelUnavailable');
                      }
                      return t('subAgentPool.tooltip.unavailableAgent');
                    })()}
                  >
                    <ExclamationCircleOutlined className="text-amber-500 text-sm flex-shrink-0 cursor-pointer" />
                  </Tooltip>
                )}
                {agent.is_new && (
                  <Tooltip title={t("space.new", "New imported agent")}>
                    <span className="inline-flex items-center px-1 h-5 bg-amber-50 text-amber-700 rounded-full text-[11px] font-medium border border-amber-200 flex-shrink-0 leading-none">
                      <span className="px-0.5">{t("space.new", "NEW")}</span>
                    </span>
                  </Tooltip>
                )}
                {displayName && (
                  <span className="truncate text-sm">{displayName}</span>
                )}
              </Flex>
              <div>
              {agent.is_a2a_server && (
                  <Tooltip title={t("a2a.agent.viewA2ASettings")}>
                    <span>
                      <Button
                        type="text"
                        size="small"
                        icon={<Globe className="w-4 h-4"/>}
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          handleViewA2AAgentSettings(agent);
                        }}
                        className="agent-action-button agent-action-button-blue"
                      />
                    </span>
                  </Tooltip>
                )}
                <Tooltip title={t("agent.contextMenu.copy")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<Copy className="w-4 h-4" />}
                    disabled={!isAvailable}
                    className="agent-action-button agent-action-button-blue"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleCopyAgentWithConfirm(agent);
                    }}
                  />
                </Tooltip>
                <Tooltip title={t("agent.action.viewCallRelationship")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<Network className="w-4 h-4" />}
                    disabled={!isAvailable}
                    className="agent-action-button agent-action-button-blue"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleViewCallRelationship(agent);
                    }}
                  />
                </Tooltip>
                <Tooltip title={t("agent.contextMenu.export")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<FileOutput className="w-4 h-4" />}
                    disabled={!isAvailable}
                    className="agent-action-button agent-action-button-green"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleExportAgent(agent);
                    }}
                  />
                </Tooltip>
                <Tooltip
                  title={
                    agent.permission === "READ_ONLY"
                      ? t("agent.noEditPermission")
                      : t("agent.contextMenu.delete")
                  }
                >
                  <Button
                    type="text"
                    size="small"
                    icon={<Trash2 className="w-4 h-4" />}
                    disabled={agent.permission === "READ_ONLY"}
                    className="agent-action-button agent-action-button-red"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteAgentWithConfirm(agent);
                    }}
                  />
                </Tooltip>
              </div>
            </div>
          </div>
          {/* Row 2: Description */}
          <div
            className={`text-xs truncate min-w-0 ${!isAvailable ? "text-gray-400" : "text-gray-500"}`}
          >
            {agent.description}
          </div>
        </Flex>
        </div>
      ),
      onClick: () => handleSelectAgent(Number(agent.id)),
    };

    // Add divider after each item except the last one
    const divider = index < agents.length - 1
      ? { key: `divider-${agent.id}`, type: 'divider' as const }
      : null;

    return divider ? [agentItem, divider] : [agentItem];
  });

  return (
    <>
      <div className="w-full h-full px-6" style={{ borderBottom: "1px solid #f0f0f0" }}>
        <Row
          gutter={{ lg: 32, md: 32, sm: 16 }}
          className="h-full px-4"
          align="middle"
        >
          {/* Left column: Agent Config */}
          <Col
            xs={24}
            sm={24}
            md={24}
            lg={12}
            className="flex min-w-0"
          >
            <Dropdown
              trigger={["click"]}
              placement="bottomLeft"
              open={dropdownOpen}
              onOpenChange={setDropdownOpen}
              menu={{ 
                items: agentMenuItems,
                style: { maxHeight: 500, overflowY: 'auto' }
              }}
              getPopupContainer={(triggerNode) => triggerNode.parentNode as HTMLElement}
              styles={{
                root: {
                  width: 'calc(100% - 32px)',
                }
              }}
            >
              <div
                className="flex items-center gap-2 py-2 pr-2 cursor-pointer hover:bg-gray-50 rounded-md transition-colors w-full overflow-hidden"
              >
                <div className="relative w-12 h-12 rounded-lg bg-blue-100 flex items-center justify-center flex-shrink-0 mx-2">
                  {hasUnsavedChanges && (
                    <Badge dot color="blue" style={{ position: "absolute", top: -8, right: -8 }} >
                      <Bot className="w-8 h-8 text-blue-600" />
                    </Badge>
                  )}
                  {!hasUnsavedChanges && <Bot className="w-8 h-8 text-blue-600" />}
                </div>
                <div className="flex-1 min-w-0 mx-2">
                  <div className="text-lg font-medium text-gray-900 leading-tight mb-2">
                    {isCreatingMode
                      ? t("agent.action.create")
                      : currentAgent?.display_name || currentAgent?.name || t("agentConfig.agents.selectAgent")}
                  </div>
                  <div className="text-sm text-gray-500 leading-tight truncate">
                    {isCreatingMode
                    ? t("agent.action.createOrSelect")
                    : currentAgent?.description || t("agentConfig.agents.noAgentSelected")}
                  </div>
                </div>
                <ChevronDown className="w-4 h-4 text-gray-400 flex-shrink-0" />
              </div>
            </Dropdown>


          </Col>
          {/* Right column: Agent Info */}
          <Col
            xs={24}
            sm={24}
            md={24}
            lg={12}
            className="flex justify-end"
          >
          {currentAgentId != null && agentInfo?.current_version_no !== 0 && total > 0 && (
              <Flex
                align="center"
                gap={4}
                className="py-1.5 px-3 bg-gray-100 rounded-lg text-gray-700"
              >
                <History size={16} />

                <Tag color="cyan" variant="outlined" className="rounded-md font-mono text-sm">
                  {agentVersionDetail?.version.version_name} 
                </Tag>
                <span className="text-xs text-gray-500 ml-1">
                / {t("agent.version.totalVersions", { count: total ?? 0 })}
                </span>
              </Flex>
            )}
          {/* Right side: Agent count + Version management button */}
          <Flex align="center" gap={12} className="mr-6">
            {/* Create and Import buttons outside dropdown */}
            <Flex align="center" gap={8} className="ml-4">
              <Button
                size="middle"
                onClick={enterCreateMode}
                className="flex items-center gap-1"
              >
                <Plus className="w-4 h-4" />
                <span>{t("agentConfig.button.new")}</span>
              </Button>
              <Button
                size="middle"
                onClick={handleImportAgent}
                className="flex items-center gap-1"
              >
                <FileInput className="w-4 h-4" />
                <span>{t("agentConfig.button.import")}</span>
              </Button>
            </Flex>

            <Button
              icon={<GitBranch size={16} />}
              onClick={isShowVersionManagePanel ? onCloseVersionManagePanel : onOpenVersionManage}
              type={isShowVersionManagePanel ? "primary" : "default"}
            >
              {t("agent.version.manage")}
            </Button>
          </Flex>
          </Col>
        </Row>

      </div>

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
          queryClient.invalidateQueries({ queryKey: ["agents"] });
        }}
      />

      {/* Call Relationship Modal */}
      {selectedAgentForRelationship && (
        <AgentCallRelationshipModal
          visible={callRelationshipModalVisible}
          onClose={handleCloseCallRelationshipModal}
          agentId={Number(selectedAgentForRelationship.id)}
          agentName={
            selectedAgentForRelationship.display_name ||
            selectedAgentForRelationship.name
          }
          
        />
      )}

      {/* A2A Server Settings Modal */}
      <Modal
        centered
        width={640}
        title={t("a2a.server.previewTitle")}
        open={showA2ASettings}
        onCancel={() => {
          setShowA2ASettings(false);
          setSelectedAgentForA2A(null);
        }}
        loading={isLoadingA2ASettings}
        footer={null}
        zIndex={1050}
      >
        {selectedAgentForA2A && constructedA2AAgentCard ? (
          <A2AServerSettingsPanel
            agentId={Number(selectedAgentForA2A.id)}
            agentName={selectedAgentForA2A.display_name || selectedAgentForA2A.name}
            endpointId={constructedA2AAgentCard.endpoint_id}
            a2aAgentCard={constructedA2AAgentCard}
          />
        ) : (
          <div style={{ textAlign: "center", padding: "40px 0", color: "#999" }}>
            {t("a2a.service.getServerSettingsFailed", "Failed to load A2A settings")}
          </div>
        )}
      </Modal>
    </>
  );
}
