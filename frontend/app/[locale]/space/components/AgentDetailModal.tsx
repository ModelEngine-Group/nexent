"use client";

import React from "react";
import { Modal, Tabs, Tag, Descriptions, Empty, Avatar } from "antd";
import { useTranslation } from "react-i18next";
import {
  CheckCircle,
  XCircle,
  Bot,
  Settings,
  FileText,
  Wrench,
  Users,
  Sparkles,
} from "lucide-react";
// Using AntD Avatar directly in this component
import { generateAvatarFromName } from "@/lib/avatar";
import { getToolSourceLabel, getCategoryLabel } from "@/lib/agentLabelMapper";
import { getLocalizedDescription } from "@/lib/utils";

interface AgentDetailModalProps {
  visible: boolean;
  onClose: () => void;
  agentDetails: any;
  loading: boolean;
}

export default function AgentDetailModal({
  visible,
  onClose,
  agentDetails,
  loading,
}: AgentDetailModalProps) {
  const { t } = useTranslation("common");

  if (!agentDetails && !loading) {
    return null;
  }

  // Generate avatar URL from agent name (same as AgentCard)
  const avatarUrl = agentDetails 
    ? generateAvatarFromName(agentDetails.display_name || agentDetails.name)
    : "";

  const items = [
    {
      key: "basic",
      label: (
        <span className="flex items-center gap-2">
          <Bot className="h-4 w-4" />
          {t("space.detail.tabs.basic", "Basic Info")}
        </span>
      ),
      children: (
        <div className="space-y-4">
          <Descriptions column={1} bordered labelStyle={{ fontWeight: 600, whiteSpace: 'nowrap' }}>
            <Descriptions.Item label={t("space.detail.id", "Agent ID")}>
              {agentDetails?.id || "-"}
            </Descriptions.Item>
            <Descriptions.Item label={t("space.detail.name", "Name")}>
              {agentDetails?.name || "-"}
            </Descriptions.Item>
            <Descriptions.Item label={t("space.detail.displayName", "Display Name")}>
              {agentDetails?.display_name || "-"}
            </Descriptions.Item>
            <Descriptions.Item label={t("space.detail.description", "Description")}>
              {agentDetails?.description || "-"}
            </Descriptions.Item>
            <Descriptions.Item label={t("space.detail.status", "Status")}>
              {agentDetails?.is_available ? (
                <Tag icon={<CheckCircle className="h-3 w-3" />} color="success" className="inline-flex items-center gap-1">
                  <span className="whitespace-nowrap">{t("space.status.available", "Available")}</span>
                </Tag>
              ) : (
                <Tag icon={<XCircle className="h-3 w-3" />} color="error" className="inline-flex items-center gap-1">
                  <span className="whitespace-nowrap">{t("space.status.unavailable", "Unavailable")}</span>
                </Tag>
              )}
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
          {t("space.detail.tabs.model", "Model Config")}
        </span>
      ),
      children: (
        <div className="space-y-4">
          <Descriptions column={1} bordered labelStyle={{ fontWeight: 600, whiteSpace: 'nowrap' }}>
          <Descriptions.Item label={t("space.detail.businessLogicModel", "Business Logic Model")}>
              {agentDetails?.business_logic_model_name || "-"}
            </Descriptions.Item>
            <Descriptions.Item label={t("space.detail.model", "Model Name")}>
              {agentDetails?.model || "-"}
            </Descriptions.Item>
            <Descriptions.Item label={t("space.detail.maxStep", "Max Steps")}>
              {agentDetails?.max_step || 0}
            </Descriptions.Item>
            <Descriptions.Item label={t("space.detail.provideRunSummary", "Provide Run Summary")}>
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
          {t("space.detail.tabs.prompts", "Prompts")}
        </span>
      ),
      children: (
        <div className="space-y-4">
          <div>
            <h4 className="font-semibold mb-2 flex items-center gap-2">
              <Sparkles className="h-4 w-4" />
              {t("space.detail.dutyPrompt", "Duty Prompt")}
            </h4>
            <div className="p-3 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
              <pre className="whitespace-pre-wrap text-sm">
                {agentDetails?.duty_prompt || t("common.none", "None")}
              </pre>
            </div>
          </div>
          <div>
            <h4 className="font-semibold mb-2 flex items-center gap-2">
              <FileText className="h-4 w-4" />
              {t("space.detail.constraintPrompt", "Constraint Prompt")}
            </h4>
            <div className="p-3 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
              <pre className="whitespace-pre-wrap text-sm">
                {agentDetails?.constraint_prompt || t("common.none", "None")}
              </pre>
            </div>
          </div>
          <div>
            <h4 className="font-semibold mb-2 flex items-center gap-2">
              <FileText className="h-4 w-4" />
              {t("space.detail.fewShotsPrompt", "Few-Shots Prompt")}
            </h4>
            <div className="p-3 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
              <pre className="whitespace-pre-wrap text-sm">
                {agentDetails?.few_shots_prompt || t("common.none", "None")}
              </pre>
            </div>
          </div>
          <div>
            <h4 className="font-semibold mb-2 flex items-center gap-2">
              <FileText className="h-4 w-4" />
              {t("space.detail.businessDescription", "Business Description")}
            </h4>
            <div className="p-3 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
              <pre className="whitespace-pre-wrap text-sm">
                {agentDetails?.business_description || t("common.none", "None")}
              </pre>
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
          {t("space.detail.tabs.tools", "Tools")} ({agentDetails?.tools?.length || 0})
        </span>
      ),
      children: (
        <div className="space-y-3">
          {agentDetails?.tools && agentDetails.tools.length > 0 ? (
            agentDetails.tools.map((tool: any) => (
              <div
                key={tool.id}
                className="p-4 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700"
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex-1">
                    <h4 className="font-semibold text-base">{tool.name}</h4>
                    <p className="text-sm text-slate-600 dark:text-slate-300 mt-1">
                      {getLocalizedDescription(tool.description, tool.description_zh) || t("space.noDescription", "No description")}
                    </p>
                  </div>
                  {tool.is_available ? (
                    <Tag icon={<CheckCircle className="h-3 w-3" />} color="success" className="inline-flex items-center gap-1 ml-2">
                      <span className="whitespace-nowrap">{t("space.status.available", "Available")}</span>
                    </Tag>
                  ) : (
                    <Tag icon={<XCircle className="h-3 w-3" />} color="error" className="inline-flex items-center gap-1 ml-2">
                      <span className="whitespace-nowrap">{t("space.status.unavailable", "Unavailable")}</span>
                    </Tag>
                  )}
                </div>
                <div className="flex gap-2 flex-wrap">
                  {tool.source && (
                    <Tag color="blue">
                      {t("common.source", "Source")}: {getToolSourceLabel(tool.source, t)}
                    </Tag>
                  )}
                  {tool.category && (
                    <Tag color="purple">
                      {t("common.category", "Category")}: {getCategoryLabel(tool.category, t)}
                    </Tag>
                  )}
                  {tool.usage && (
                    <Tag color="green">
                      {t("common.usage", "Usage")}: {tool.usage}
                    </Tag>
                  )}
                </div>
                {(() => {
                  let parsedInputs: Record<string, any> = {};
                  try {
                    parsedInputs = tool.inputs ? JSON.parse(tool.inputs) : {};
                  } catch {
                    parsedInputs = {};
                  }
                  return Object.keys(parsedInputs).length > 0 ? (
                    <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-600">
                      <div className="text-xs font-semibold text-slate-600 dark:text-slate-400 mb-2">
                        {t("space.detail.inputParameters", "Input Parameters")}:
                      </div>
                      <div className="space-y-2">
                        {Object.entries(parsedInputs).map(([key, value]) => (
                          <div key={key} className="text-xs">
                            <span className="font-medium">{key}</span>
                            <span className="text-slate-500 dark:text-slate-400 ml-2">
                              ({value.type})
                            </span>
                            {getLocalizedDescription(value.description, value.description_zh) && (
                              <div className="text-slate-600 dark:text-slate-300 mt-1">
                                {getLocalizedDescription(value.description, value.description_zh)}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : null;
                })()}
                {tool.initParams && tool.initParams.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-600">
                    <div className="text-xs font-semibold text-slate-600 dark:text-slate-400 mb-2">
                      {t("space.detail.parameters", "Parameters")}:
                    </div>
                    <div className="space-y-2">
                      {tool.initParams.map((param: any, idx: number) => (
                        <div key={idx} className="text-xs">
                          <span className="font-medium">{param.name}</span>
                          {param.required && (
                            <Tag color="red" className="ml-1 text-xs">
                              {t("common.required", "Required")}
                            </Tag>
                          )}
                          <span className="text-slate-500 dark:text-slate-400 ml-2">
                            ({param.type})
                          </span>
                          {getLocalizedDescription(param.description, param.description_zh) && (
                            <div className="text-slate-600 dark:text-slate-300 mt-1">
                              {getLocalizedDescription(param.description, param.description_zh)}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))
          ) : (
            <Empty
              description={t("space.detail.noTools", "No tools configured")}
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          )}
        </div>
      ),
    },
    {
      key: "subAgents",
      label: (
        <span className="flex items-center gap-2">
          <Users className="h-4 w-4" />
          {t("space.detail.tabs.subAgents", "Sub Agents")} (
          {agentDetails?.sub_agent_id_list?.length || 0})
        </span>
      ),
      children: (
        <div className="space-y-3">
          {agentDetails?.sub_agent_id_list && agentDetails.sub_agent_id_list.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {agentDetails.sub_agent_id_list.map((subAgentId: string) => (
                <div
                  key={subAgentId}
                  className="p-3 bg-slate-50 dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700"
                >
                  <div className="flex items-center gap-2">
                    <Bot className="h-4 w-4 text-blue-500" />
                    <span className="font-medium">{t("space.detail.subAgentId", "Sub Agent ID")}:</span>
                    <span className="text-slate-600 dark:text-slate-300">{subAgentId}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Empty
              description={t("space.detail.noSubAgents", "No sub agents configured")}
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
          <Avatar src={avatarUrl} size={40} className="w-10 h-10">
            <span className="bg-gradient-to-br from-blue-100 to-blue-200 dark:from-blue-900/30 dark:to-blue-800/30 text-lg font-bold text-blue-600 dark:text-blue-400">
              {agentDetails?.display_name?.charAt(0)?.toUpperCase() || agentDetails?.name?.charAt(0)?.toUpperCase() || "A"}
            </span>
          </Avatar>
          <div>
            <div className="text-lg font-semibold">
              {agentDetails?.display_name || agentDetails?.name || t("space.detail.title", "Agent Details")}
            </div>
            <div className="text-xs text-slate-500 dark:text-slate-400 font-normal">
              {t("space.detail.subtitle", "Detailed configuration and information")}
            </div>
          </div>
        </div>
      }
      open={visible}
      onCancel={onClose}
      footer={null}
      width={800}
      style={{ top: 20, maxHeight: 'calc(100vh - 40px)' }}
      styles={{ body: { maxHeight: 'calc(100vh - 180px)', overflowY: 'auto' } }}
      className="agent-detail-modal"
    >
      <div className="mt-4">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
          </div>
        ) : (
          <Tabs items={items} defaultActiveKey="basic" />
        )}
      </div>
    </Modal>
  );
}

