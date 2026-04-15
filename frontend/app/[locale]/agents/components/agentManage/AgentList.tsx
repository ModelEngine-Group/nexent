"use client";

import React from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Col, Flex, Tooltip, Divider, Table, theme, App, Modal, Spin, message } from "antd";
import { ExclamationCircleOutlined } from "@ant-design/icons";
import { Copy, FileOutput, Network, Trash2, Globe } from "lucide-react";
import { useMutation, useQueryClient, useQuery } from "@tanstack/react-query";

import { Agent } from "@/types/agentConfig";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import AgentCallRelationshipModal from "@/components/ui/AgentCallRelationshipModal";
import {
  searchAgentInfo,
  updateAgentInfo,
  deleteAgent,
  exportAgent,
  updateToolConfig,
} from "@/services/agentConfigService";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useSaveGuard } from "@/hooks/agent/useSaveGuard";
import { clearAgentNewMark } from "@/services/agentConfigService";
import { a2aClientService } from "@/services/a2aService";
import A2AServerSettingsPanel from "../a2a/A2AServerSettingsPanel";
import log from "@/lib/logger";

interface AgentListProps {
  agentList: Agent[];
}

export default function AgentList({
  agentList,
}: AgentListProps) {
  const { t } = useTranslation();
  const { token } = theme.useToken();
  const { message } = App.useApp();
  const confirm = useConfirmModal();
  const queryClient = useQueryClient();

  // Call relationship modal state
  const [callRelationshipModalVisible, setCallRelationshipModalVisible] =
    useState(false);
  const [selectedAgentForRelationship, setSelectedAgentForRelationship] =
    useState<Agent | null>(null);

  // A2A settings modal state
  const [showA2ASettings, setShowA2ASettings] = useState(false);
  const [selectedAgentForA2A, setSelectedAgentForA2A] = useState<Agent | null>(null);

  // A2A settings modal state
  const currentAgentId = useAgentConfigStore((state) => state.currentAgentId);
  const setCurrentAgent = useAgentConfigStore((state) => state.setCurrentAgent);
  const hasUnsavedChanges = useAgentConfigStore((state) => state.hasUnsavedChanges);

  // Mutations
  const updateAgentMutation = useMutation({
    mutationFn: (payload: any) => updateAgentInfo(payload),
  });

  const deleteAgentMutation = useMutation({
    mutationFn: (agentId: number) => deleteAgent(agentId),
  });

    // Unsaved changes guard
  const checkUnsavedChanges = useSaveGuard();

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

  // Handle view call relationship
  const handleViewCallRelationship = (agent: Agent) => {
    setSelectedAgentForRelationship(agent);
    setCallRelationshipModalVisible(true);
  };

  const handleCloseCallRelationshipModal = () => {
    setCallRelationshipModalVisible(false);
    setSelectedAgentForRelationship(null);
  };

  // Handle view A2A agent settings
  const handleViewA2AAgentSettings = (agent: Agent) => {
    setSelectedAgentForA2A(agent);
    setShowA2ASettings(true);
  };

  // Handle select agent
  const handleSelectAgent = async (agent: Agent) => {
    // Clear NEW mark when agent is selected for editing (only if marked as new)
    if (agent.is_new === true) {
      try {
        const res = await clearAgentNewMark(agent.id);
        if (res?.success) {
          log.warn("Failed to clear NEW mark on select:", res);
          queryClient.invalidateQueries({ queryKey: ["agents"] });
        }
      } catch (err) {
        log.error("Failed to clear NEW mark on select:", err);
      }
    }

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

    // Only guard when leaving an existing agent or exiting create mode
    if (currentAgentId !== null || useAgentConfigStore.getState().isCreatingMode) {
      const canSwitch = await checkUnsavedChanges.saveWithModal();
      if (!canSwitch) {
        return;
      }
    }

    // Load agent detail and set as current
    try {
      const result = await searchAgentInfo(Number(agent.id));
      if (result.success && result.data) {
        // Get permission from agent list (agentList prop contains permission from /agent/list)
        const permissionFromList = agent.permission ?? undefined;
        // Merge permission into agent detail before setting as current
        setCurrentAgent({
          ...result.data,
          permission: permissionFromList,
        });
      } else {
        message.error(result.message || t("agentConfig.agents.detailsLoadFailed"));
      }
    } catch (error) {
      log.error("Failed to load agent detail:", error);
      message.error(t("agentConfig.agents.detailsLoadFailed"));
    }
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

  return (
    <Col xs={24} className="h-full">
      <Flex vertical className="h-full overflow-hidden">
        <div className="text-sm font-medium text-gray-600 mb-1 px-1">
          {t("subAgentPool.section.agentList")} ({agentList.length})
        </div>
        <Divider style={{ margin: "6px 0 0 0" }} />
        <div className="flex-1 min-h-0 overflow-y-auto">
          <Table
            dataSource={agentList}
            size="middle"
            rowKey={(agent) => String(agent.id)}
            pagination={false}
            showHeader={false}
            rowClassName={(agent: any) => {
              const isSelected =
                currentAgentId !== null &&
                String(currentAgentId) === String(agent.id);
              return `py-3 px-4 transition-colors border-gray-200 h-[80px] ${
                agent.is_available === false
                  ? "opacity-60 cursor-not-allowed"
                  : "hover:bg-gray-50 cursor-pointer"
              } ${
                isSelected ? "bg-blue-50 selected-row pl-3"
                  : ""
              }`;
            }}
            onRow={(agent: any) => ({
              onClick: (e: any) => {
                e.preventDefault();
                e.stopPropagation();
                handleSelectAgent(agent);
              },
            })}
            columns={[
              {
                key: "info",
                render: (_: any, agent: Agent) => {
                  const isAvailable = agent.is_available !== false;
                  const displayName = agent.display_name || "";
                  const name = agent.name || "";
                  const isSelected =
                    currentAgentId !== null &&
                    String(currentAgentId) === String(agent.id);
                  const isNew = agent.is_new || false;

                  return (
                    <Flex
                      vertical
                      justify="center"
                      align="flex-start"
                      className="px-2"
                    >
                      <div
                        className={`font-medium text-base truncate transition-colors duration-300 ${!isAvailable ? "text-gray-500" : ""}`}
                      >
                        <div
                          className="flex items-center"
                          style={{
                            maxWidth: "100%",
                            paddingRight: 4,
                            gap: 6,
                          }}
                        >
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
                                return t('subAgentPool.tooltip.unavailableAgent'); // fallback
                              })()}
                            >
                              <ExclamationCircleOutlined className="text-amber-500 text-sm flex-shrink-0 cursor-pointer" />
                            </Tooltip>
                          )}
                          {isNew && (
                            <Tooltip title={t("space.new", "New imported agent")}>
                              <span className="inline-flex items-center px-1 h-5 bg-amber-50 dark:bg-amber-900/10 text-amber-700 dark:text-amber-300 rounded-full text-[11px] font-medium border border-amber-200 flex-shrink-0 leading-none">
                                <span className="px-0.5">{t("space.new", "NEW")}</span>
                              </span>
                            </Tooltip>
                          )}
                          {displayName && (
                            <span className="text-base leading-normal max-w-[220px] truncate break-all">
                              {displayName}
                            </span>
                          )}
                          {hasUnsavedChanges && isSelected && (
                            <span
                              aria-label="unsaved-indicator"
                              title="Unsaved changes"
                              className="ml-2 inline-block w-2.5 h-2.5 rounded-full bg-blue-500"
                            />
                          )}
                        </div>
                      </div>
                      <div
                        className={`text-xs transition-colors duration-300 leading-[1.25] agent-description break-words ${!isAvailable ? "text-gray-400" : "text-gray-500"}`}
                        style={{
                          display: "-webkit-box",
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: "vertical",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {agent.description}
                      </div>
                    </Flex>
                  );
                },
              },
              {
                key: "actions",
                width: 130,
                render: (_: any, agent: Agent) => (
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      justifyContent: "flex-end",
                    }}
                  >
                        {agent.is_a2a_server && (
                          <Tooltip title={t("a2a.agent.viewA2ASettings")}>
                            <span>
                              <Button
                                type="text"
                                size="small"
                                icon={
                                  <Globe
                                    className="w-4 h-4"
                                    style={{ color: token.colorPrimary }}
                                  />
                                }
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
                      <span>
                        <Button
                          type="text"
                          size="small"
                          icon={
                            <Copy
                              className="w-4 h-4"
                              style={{ color: token.colorPrimary }}
                            />
                          }
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            handleCopyAgentWithConfirm(agent);
                          }}
                          disabled={agent.is_available === false}
                          className="agent-action-button agent-action-button-blue"
                        />
                      </span>
                    </Tooltip>

                    <Tooltip title={t("agent.action.viewCallRelationship")}>
                      <span>
                        <Button
                          type="text"
                          size="small"
                          icon={
                            <Network
                              className="w-4 h-4"
                              style={{ color: token.colorPrimary }}
                            />
                          }
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            handleViewCallRelationship(agent);
                          }}
                          disabled={agent.is_available === false}
                          className="agent-action-button agent-action-button-blue"
                        />
                      </span>
                    </Tooltip>

                    <Tooltip title={t("agent.contextMenu.export")}>
                      <span>
                        <Button
                          type="text"
                          size="small"
                          icon={
                            <FileOutput
                              className="w-4 h-4"
                              style={{ color: token.colorSuccess }}
                            />
                          }
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            handleExportAgent(agent);
                          }}
                          disabled={agent.is_available === false}
                          className="agent-action-button agent-action-button-green"
                        />
                      </span>
                    </Tooltip>

                    <Tooltip
                      title={
                        agent.permission === "READ_ONLY"
                          ? t("agent.noEditPermission")
                          : t("agent.contextMenu.delete")
                      }
                    >
                      <span>
                        <Button
                          type="text"
                          size="small"
                          icon={
                            <Trash2
                              className="w-4 h-4"
                              style={{
                                color:
                                  agent.permission === "READ_ONLY"
                                    ? token.colorTextDisabled
                                    : token.colorError,
                              }}
                            />
                          }
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            handleDeleteAgentWithConfirm(agent);
                          }}
                          disabled={agent.permission === "READ_ONLY"}
                          className="agent-action-button agent-action-button-red"
                        />
                      </span>
                    </Tooltip>
                  </div>
                ),
              },
            ]}
          />
        </div>
      </Flex>

      {/* Agent call relationship modal */}
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

      {/* A2A Server Settings modal */}
      <Modal
        centered
        width={640}
        title={t("a2a.server.previewTitle")}
        open={showA2ASettings}
        onCancel={() => {
          setShowA2ASettings(false);
          setSelectedAgentForA2A(null);
        }}
        footer={null}
      >
        {isLoadingA2ASettings ? (
          <div style={{ textAlign: "center", padding: "40px 0" }}>
            <Spin />
          </div>
        ) : selectedAgentForA2A && constructedA2AAgentCard ? (
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
    </Col>
  );
}
