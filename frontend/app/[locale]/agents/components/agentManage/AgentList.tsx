"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Col, Flex, Tooltip, Divider, Table, theme, App } from "antd";
import { ExclamationCircleOutlined } from "@ant-design/icons";
import { Copy, FileOutput, Network, Trash2 } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Agent } from "@/types/agentConfig";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import AgentCallRelationshipModal from "@/components/ui/AgentCallRelationshipModal";
import {
  searchAgentInfo,
  updateAgent,
  deleteAgent,
  exportAgent,
  updateToolConfig,
} from "@/services/agentConfigService";
import log from "@/lib/logger";

interface AgentListProps {
  agentList: Agent[];
  currentAgentId: number | null;
  hasUnsavedChanges: boolean;
  onSelectAgent: (agent: Agent) => void;
  onAgentDeleted?: (agentId: number) => void;
}

export default function AgentList({
  agentList,
  currentAgentId,
  hasUnsavedChanges,
  onSelectAgent,
  onAgentDeleted,
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

  // Mutations
  const updateAgentMutation = useMutation({
    mutationFn: (payload: any[]) => updateAgent(...payload),
  });

  const deleteAgentMutation = useMutation({
    mutationFn: (agentId: number) => deleteAgent(agentId),
  });

  // Handle view call relationship
  const handleViewCallRelationship = (agent: Agent) => {
    setSelectedAgentForRelationship(agent);
    setCallRelationshipModalVisible(true);
  };

  const handleCloseCallRelationshipModal = () => {
    setCallRelationshipModalVisible(false);
    setSelectedAgentForRelationship(null);
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
        message.success(t("businessLogic.config.error.agentImportSuccess"));
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

      const createResult = await updateAgentMutation.mutateAsync([
        undefined,
        copyName,
        detail.description,
        detail.model,
        detail.max_step,
        detail.provide_run_summary,
        detail.enabled,
        detail.business_description,
        detail.duty_prompt,
        detail.constraint_prompt,
        detail.few_shots_prompt,
        copyDisplayName,
        detail.model_id ?? undefined,
        detail.business_logic_model_name ?? undefined,
        detail.business_logic_model_id ?? undefined,
        enabledToolIds,
        subAgentIds,
        detail.author,
      ]);

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
            name: agent.name,
          })
        );

        // Notify parent component if this was the current agent
        if (
          currentAgentId !== null &&
          String(currentAgentId) === String(agent.id)
        ) {
          onAgentDeleted?.(Number(agent.id));
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
        name: agent.name,
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
              return `py-3 px-4 transition-colors border-gray-200 h-[80px] ${
                agent.is_available === false
                  ? "opacity-60 cursor-not-allowed"
                  : "hover:bg-gray-50 cursor-pointer"
              } ${
                currentAgentId !== null &&
                String(currentAgentId) === String(agent.id)
                  ? "bg-blue-50 selected-row pl-3"
                  : ""
              }`;
            }}
            onRow={(agent: any) => ({
              onClick:
                agent.is_available === false
                  ? undefined
                  : (e: any) => {
                      e.preventDefault();
                      e.stopPropagation();
                      onSelectAgent(agent);
                    },
            })}
            columns={[
              {
                key: "info",
                render: (_: any, agent: Agent) => {
                  const isAvailable = agent.is_available !== false;
                  const displayName = agent.display_name || agent.name;
                  const isSelected =
                    currentAgentId !== null &&
                    String(currentAgentId) === String(agent.id);

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
                            <ExclamationCircleOutlined className="text-amber-500 text-sm flex-shrink-0" />
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
                      justifyContent: "flex-center",
                    }}
                  >
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
                          className="agent-action-button agent-action-button-green"
                        />
                      </span>
                    </Tooltip>

                    <Tooltip title={t("agent.contextMenu.delete")}>
                      <span>
                        <Button
                          type="text"
                          size="small"
                          icon={
                            <Trash2
                              className="w-4 h-4"
                              style={{ color: token.colorError }}
                            />
                          }
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            handleDeleteAgentWithConfirm(agent);
                          }}
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
    </Col>
  );
}
