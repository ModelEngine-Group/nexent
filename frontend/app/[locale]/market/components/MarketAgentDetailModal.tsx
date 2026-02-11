"use client";

import React from "react";
import { Modal, Tabs, Tag, Descriptions, Empty } from "antd";
import { useTranslation } from "react-i18next";
import {
  Bot,
  Settings,
  FileText,
  Wrench,
  Server,
  Sparkles,
} from "lucide-react";
import { MarketAgentDetail } from "@/types/market";
import { getToolSourceLabel, getGenericLabel } from "@/lib/agentLabelMapper";
import { getCategoryIcon } from "@/const/marketConfig";
import { getLocalizedDescription } from "@/lib/utils";
import { useLocalTools } from "@/hooks/useLocalTools";

interface MarketAgentDetailModalProps {
  visible: boolean;
  onClose: () => void;
  agentDetails: MarketAgentDetail | null;
  loading: boolean;
}

/**
 * Market Agent Detail Modal
 * Displays complete agent information from the marketplace
 */
export default function MarketAgentDetailModal({
  visible,
  onClose,
  agentDetails,
  loading,
}: MarketAgentDetailModalProps) {
  const { t, i18n } = useTranslation("common");
  const isZh = i18n.language === "zh" || i18n.language === "zh-CN";
  const { localTools } = useLocalTools();

  if (!agentDetails && !loading) {
    return null;
  }

  /**
   * Check if field value needs configuration
   * Returns true if value is "<TO_CONFIG>"
   */
  const needsConfig = (value: any): boolean => {
    return typeof value === "string" && value.trim() === "<TO_CONFIG>";
  };

  /**
   * Render field value with config tag if needed
   */
  const renderFieldValue = (value: any): React.ReactNode => {
    if (needsConfig(value)) {
      return (
        <Tag color="orange" className="inline-flex items-center gap-1">
          <span className="whitespace-nowrap">
            {t("common.toBeConfigured", "To Be Configured")}
          </span>
        </Tag>
      );
    }
    return value || "-";
  };


  const items = [
    {
      key: "basic",
      label: (
        <span className="flex items-center gap-2">
          <Bot className="h-4 w-4" />
          {t("market.detail.tabs.basic", "Basic Info")}
        </span>
      ),
      children: (
        <div className="space-y-4">
          <Descriptions
            column={1}
            bordered
            labelStyle={{ fontWeight: 600, whiteSpace: "nowrap" }}
          >
            <Descriptions.Item label={t("market.detail.name", "Name")}>
              {agentDetails?.name || "-"}
            </Descriptions.Item>
            <Descriptions.Item
              label={t("market.detail.displayName", "Display Name")}
            >
              {agentDetails?.display_name || "-"}
            </Descriptions.Item>
            <Descriptions.Item
              label={t("market.detail.author", "Author")}
            >
              {agentDetails?.author || "-"}
            </Descriptions.Item>
            <Descriptions.Item
              label={t("market.detail.description", "Description")}
            >
              {renderFieldValue(agentDetails?.description)}
            </Descriptions.Item>
            <Descriptions.Item
              label={t("market.detail.category", "Category")}
            >
              {agentDetails?.category ? (
                <Tag color="purple" className="inline-flex items-center gap-1">
                  <span>
                    {agentDetails.category.icon ||
                      getCategoryIcon(agentDetails.category.name)}
                  </span>
                  <span>
                    {isZh
                      ? agentDetails.category.display_name_zh
                      : agentDetails.category.display_name}
                  </span>
                </Tag>
              ) : (
                <Tag color="default" className="inline-flex items-center gap-1">
                  <span>📦</span>
                  <span>{isZh ? "其他" : "Other"}</span>
                </Tag>
              )}
            </Descriptions.Item>
            <Descriptions.Item label={t("market.detail.tags", "Tags")}>
              {agentDetails?.tags && agentDetails.tags.length > 0 ? (
                <div className="flex flex-wrap gap-1">
                  {agentDetails.tags.map((tag) => (
                    <Tag key={tag.id} color="blue">
                      {getGenericLabel(tag.display_name, t)}
                    </Tag>
                  ))}
                </div>
              ) : (
                "-"
              )}
            </Descriptions.Item>
            <Descriptions.Item
              label={t("market.detail.downloadCount", "Download Count")}
            >
              {agentDetails?.download_count || 0}
            </Descriptions.Item>
            <Descriptions.Item
              label={t("market.detail.createdAt", "Created At")}
            >
              {agentDetails?.created_at
                ? new Date(agentDetails.created_at).toLocaleString()
                : "-"}
            </Descriptions.Item>
            <Descriptions.Item
              label={t("market.detail.updatedAt", "Updated At")}
            >
              {agentDetails?.updated_at
                ? new Date(agentDetails.updated_at).toLocaleString()
                : "-"}
            </Descriptions.Item>
          </Descriptions>
        </div>
      ),
    },
    {
      key: "model",
      label: (
        <span className="flex items-center gap-2">
          <Settings className="h-4 w-4" />
          {t("market.detail.tabs.model", "Model Config")}
        </span>
      ),
      children: (
        <div className="space-y-4">
          <Descriptions
            column={1}
            bordered
            labelStyle={{ fontWeight: 600, whiteSpace: "nowrap" }}
          >
            <Descriptions.Item
              label={t("market.detail.maxSteps", "Max Steps")}
            >
              {agentDetails?.max_steps || 0}
            </Descriptions.Item>
            <Descriptions.Item
              label={t("market.detail.recommendedModel", "Recommended Model")}
            >
              {renderFieldValue(agentDetails?.model_name)}
            </Descriptions.Item>
            <Descriptions.Item
              label={t(
                "market.detail.provideRunSummary",
                "Provide Run Summary"
              )}
            >
              {agentDetails?.provide_run_summary ? (
                <Tag color="green">{t("common.yes", "Yes")}</Tag>
              ) : (
                <Tag color="red">{t("common.no", "No")}</Tag>
              )}
            </Descriptions.Item>
          </Descriptions>
        </div>
      ),
    },
    {
      key: "prompts",
      label: (
        <span className="flex items-center gap-2">
          <FileText className="h-4 w-4" />
          {t("market.detail.tabs.prompts", "Prompts")}
        </span>
      ),
      children: (
        <div className="space-y-4">
          <div>
            <h4 className="font-semibold mb-2 flex items-center gap-2">
              <Sparkles className="h-4 w-4" />
              {t("market.detail.dutyPrompt", "Duty Prompt")}
            </h4>
            <div className="p-3 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
              {needsConfig(agentDetails?.duty_prompt) ? (
                renderFieldValue(agentDetails?.duty_prompt)
              ) : (
                <pre className="whitespace-pre-wrap text-sm">
                  {agentDetails?.duty_prompt || t("common.none", "None")}
                </pre>
              )}
            </div>
          </div>
          <div>
            <h4 className="font-semibold mb-2 flex items-center gap-2">
              <FileText className="h-4 w-4" />
              {t("market.detail.constraintPrompt", "Constraint Prompt")}
            </h4>
            <div className="p-3 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
              {needsConfig(agentDetails?.constraint_prompt) ? (
                renderFieldValue(agentDetails?.constraint_prompt)
              ) : (
                <pre className="whitespace-pre-wrap text-sm">
                  {agentDetails?.constraint_prompt || t("common.none", "None")}
                </pre>
              )}
            </div>
          </div>
          <div>
            <h4 className="font-semibold mb-2 flex items-center gap-2">
              <FileText className="h-4 w-4" />
              {t("market.detail.fewShotsPrompt", "Few-Shots Prompt")}
            </h4>
            <div className="p-3 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
              {needsConfig(agentDetails?.few_shots_prompt) ? (
                renderFieldValue(agentDetails?.few_shots_prompt)
              ) : (
                <pre className="whitespace-pre-wrap text-sm">
                  {agentDetails?.few_shots_prompt || t("common.none", "None")}
                </pre>
              )}
            </div>
          </div>
          <div>
            <h4 className="font-semibold mb-2 flex items-center gap-2">
              <FileText className="h-4 w-4" />
              {t("market.detail.businessDescription", "Business Description")}
            </h4>
            <div className="p-3 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
              {needsConfig(agentDetails?.business_description) ? (
                renderFieldValue(agentDetails?.business_description)
              ) : (
                <pre className="whitespace-pre-wrap text-sm">
                  {agentDetails?.business_description || t("common.none", "None")}
                </pre>
              )}
            </div>
          </div>
        </div>
      ),
    },
    {
      key: "tools",
      label: (
        <span className="flex items-center gap-2">
          <Wrench className="h-4 w-4" />
          {t("market.detail.tabs.tools", "Tools")} (
          {agentDetails?.tools?.length || 0})
        </span>
      ),
      children: (
        <div className="space-y-3">
          {agentDetails?.tools && agentDetails.tools.length > 0 ? (
            agentDetails.tools.map((tool) => {
              const localTool = tool.source === "local" ? localTools[tool.name] : null;
              const mergedTool = localTool ? {
                ...tool,
                description_zh: localTool.description_zh,
                inputs: localTool.inputs
              } : tool;

              return (
                <div
                  key={tool.id}
                  className="p-4 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700"
                >
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex-1">
                      <h4 className="font-semibold text-base">{mergedTool.name}</h4>
                      <div className="text-sm text-slate-600 dark:text-slate-300 mt-1">
                        {needsConfig(getLocalizedDescription(mergedTool.description, mergedTool.description_zh)) ? (
                          renderFieldValue(getLocalizedDescription(mergedTool.description, mergedTool.description_zh))
                        ) : (
                          getLocalizedDescription(mergedTool.description, mergedTool.description_zh) ||
                          t("market.detail.toolDescription", "No description")
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex gap-2 flex-wrap">
                    {mergedTool.source && (
                      <Tag color="blue">
                        {t("common.source", "Source")}: {getToolSourceLabel(mergedTool.source, t)}
                      </Tag>
                    )}
                    {mergedTool.usage && (
                      <Tag color="green">
                        {t("common.usage", "Usage")}: {mergedTool.usage}
                      </Tag>
                    )}
                    {mergedTool.output_type && (
                      <Tag color="purple">
                        {t("common.output", "Output")}: {mergedTool.output_type}
                      </Tag>
                    )}
                  </div>
                  {(() => {
                    let inputsObj: Record<string, any> = {};
                    if (mergedTool.inputs) {
                      if (Array.isArray(mergedTool.inputs)) {
                        inputsObj = {};
                        mergedTool.inputs.forEach((item: any, index: number) => {
                          if (item && (item.name || item.type)) {
                            inputsObj[item.name || String(index)] = item;
                          }
                        });
                      } else if (typeof mergedTool.inputs === 'string') {
                        try {
                          const parsed = JSON.parse(mergedTool.inputs);
                          if (Array.isArray(parsed)) {
                            inputsObj = {};
                            parsed.forEach((item: any, index: number) => {
                              if (item && (item.name || item.type)) {
                                inputsObj[item.name || String(index)] = item;
                              }
                            });
                          } else {
                            inputsObj = parsed;
                          }
                        } catch {
                          inputsObj = {};
                        }
                      } else {
                        inputsObj = mergedTool.inputs;
                      }
                    }
                    return Object.keys(inputsObj).length > 0 ? (
                      <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-600">
                        <div className="text-xs font-semibold text-slate-600 dark:text-slate-400 mb-2">
                          {t("market.detail.inputParameters", "Input Parameters")}:
                        </div>
                        <div className="space-y-2">
                          {Object.entries(inputsObj).map(([key, value]) => (
                            <div key={key} className="text-xs">
                              <span className="font-medium">{value.name || key}</span>
                              <span className="text-slate-500 dark:text-slate-400 ml-2">
                                ({value.type})
                              </span>
                              {getLocalizedDescription(value.description, value.description_zh) ? (
                                <div className="text-slate-600 dark:text-slate-300 mt-1">
                                  {getLocalizedDescription(value.description, value.description_zh)}
                                </div>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null;
                  })()}
                </div>
              );
            })
          ) : (
            <Empty
              description={t("market.detail.noTools", "No tools configured")}
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          )}
        </div>
      ),
    },
    {
      key: "mcpServers",
      label: (
        <span className="flex items-center gap-2">
          <Server className="h-4 w-4" />
          {t("market.detail.tabs.mcpServers", "MCP Servers")} (
          {agentDetails?.mcp_servers?.length || 0})
        </span>
      ),
      children: (
        <div className="space-y-3">
          {agentDetails?.mcp_servers && agentDetails.mcp_servers.length > 0 ? (
            agentDetails.mcp_servers.map((server) => (
              <div
                key={server.id}
                className="p-4 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700"
              >
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <Server className="h-4 w-4 text-purple-500" />
                    <span className="font-semibold">
                      {t("market.detail.mcpServerName", "Server Name")}:
                    </span>
                    <span className="text-slate-600 dark:text-slate-300">
                      {renderFieldValue(server.mcp_server_name)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">
                      {t("market.detail.mcpServerUrl", "Server URL")}:
                    </span>
                    <div className="text-slate-600 dark:text-slate-300 break-all">
                      {renderFieldValue(server.mcp_url)}
                    </div>
                  </div>
                </div>
              </div>
            ))
          ) : (
            <Empty
              description={t(
                "market.detail.noMcpServers",
                "No MCP servers configured"
              )}
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          )}
        </div>
      ),
    },
  ];

  return (
    <Modal
      title={
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-gradient-to-br from-purple-500 to-indigo-500 flex items-center justify-center">
            <Bot className="h-6 w-6 text-white" />
          </div>
          <div>
            <div className="text-lg font-semibold">
              {agentDetails?.display_name ||
                agentDetails?.name ||
                t("market.detail.title", "Agent Details")}
            </div>
            <div className="text-xs text-slate-500 dark:text-slate-400 font-normal">
              {t("market.detail.subtitle", "Complete information and configuration")}
            </div>
          </div>
        </div>
      }
      open={visible}
      onCancel={onClose}
      footer={null}
      width={800}
      style={{ top: 20, maxHeight: "calc(100vh - 40px)" }}
      styles={{ body: { maxHeight: "calc(100vh - 180px)", overflowY: "auto" } }}
      className="market-agent-detail-modal"
    >
      <div className="mt-4">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-purple-500"></div>
          </div>
        ) : (
          <Tabs items={items} defaultActiveKey="basic" />
        )}
      </div>
    </Modal>
  );
}

