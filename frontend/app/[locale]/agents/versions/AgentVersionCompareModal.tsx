// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState } from "react";
import {
  AssistantRuntimeProvider,
  type AssistantRuntime,
} from "@assistant-ui/react";
import { useTranslation } from "react-i18next";
import {
  Modal,
  Flex,
  Spin,
  Empty,
  Table,
  Tag,
  Typography,
  Button,
  Select,
  Tabs,
} from "antd";
import {
  AlertTriangle,
  RotateCcw,
  FileText,
  Wrench,
  Bot,
  PencilLine,
} from "lucide-react";

import type {
  AgentVersionDetail,
  VersionCompareResponse,
} from "@/services/agentVersionService";
import type { Agent } from "@/types/agentConfig";
import { Thread } from "@/app/newchat/assistant-ui/thread";
import { Composer, type ChatMode } from "@/app/newchat/assistant-ui/composer";
import { TooltipProvider } from "@/components/ui/tooltip";
import { deriveModelOptions } from "@/features/model-controls/modelOptions";
import { useModelList } from "@/hooks/model/useModelList";
import { AgentDebugWelcome } from "../[agentId]/components/debug/agent-debug-welcome";
import { AgentComparisonLayout } from "../components/agent-comparison-layout";
import { useVersionCompareRuntime } from "./useVersionCompareRuntime";
import "../[agentId]/components/debug/agent-debug.css";

const { Text } = Typography;

export interface AgentVersionCompareModalProps {
  open: boolean;
  loading: boolean;
  compareData: VersionCompareResponse | null;
  onCancel: () => void;
  agentId?: number | null;
  /**
   * Whether to show rollback confirm action.
   * If true, confirm button and rollback title will be used.
   */
  showRollback?: boolean;
  onRollbackConfirm?: () => void;
  rollbackLoading?: boolean;
  /**
   * Version select data and handlers.
   * When provided, version columns will render Select components for switching versions.
   */
  versionList?: { version_no: number; version_name?: string | null }[];
  currentVersionNo?: number;
  selectedVersionNoA?: number | null;
  selectedVersionNoB?: number | null;
  onChangeVersionA?: (versionNo: number) => void;
  onChangeVersionB?: (versionNo: number) => void;
}

export default function AgentVersionCompareModal({
  open,
  loading,
  compareData,
  onCancel,
  agentId,
  showRollback = false,
  onRollbackConfirm,
  rollbackLoading = false,
  versionList,
  currentVersionNo,
  selectedVersionNoA,
  selectedVersionNoB,
  onChangeVersionA,
  onChangeVersionB,
}: AgentVersionCompareModalProps) {
  const { t } = useTranslation("common");
  const [activeTab, setActiveTab] = useState("configuration");
  const [preferredModelId, setPreferredModelId] = useState<string>();
  const [chatMode, setChatMode] = useState<ChatMode>("execution");
  const { availableLlmModels } = useModelList({ enabled: open });
  const versionA = compareData?.data?.version_a;
  const versionB = compareData?.data?.version_b;
  const leftVersionNo =
    selectedVersionNoA ?? versionA?.version.version_no ?? null;
  const rightVersionNo =
    selectedVersionNoB ?? versionB?.version.version_no ?? null;
  const {
    leftRuntime,
    rightRuntime,
    isCompareStreaming,
    isCompareReady,
    runCompare,
    stopCompare,
    resetCompareState,
  } = useVersionCompareRuntime({
    agentId,
    leftVersionNo,
    rightVersionNo,
    open,
  });
  const versionOptions =
    versionList?.map((version) => {
      const baseLabel = version.version_name || `V${version.version_no}`;
      const isCurrent =
        currentVersionNo !== undefined &&
        version.version_no === currentVersionNo;
      return {
        value: version.version_no,
        label: isCurrent
          ? `${baseLabel} (${t("agent.version.currentVersion")})`
          : baseLabel,
      };
    }) ?? [];

  const footer = showRollback
    ? [
        <Button key="cancel" onClick={onCancel}>
          {t("common.cancel")}
        </Button>,
        <Button
          key="confirm"
          type="primary"
          danger
          icon={<RotateCcw size={14} />}
          loading={rollbackLoading}
          onClick={onRollbackConfirm}
        >
          {t("agent.version.confirmRollback")}
        </Button>,
      ]
    : null;

  const handleClose = () => {
    stopCompare();
    onCancel();
  };

  const resolveVersionLabel = (versionNo: number | null | undefined) => {
    if (versionNo === null || versionNo === undefined) return "-";
    const matched = versionList?.find((v) => v.version_no === versionNo);
    const detail = [versionA, versionB].find(
      (version) => version?.version.version_no === versionNo
    );
    return (
      matched?.version_name || detail?.version.version_name || `V${versionNo}`
    );
  };

  const canAsk =
    Boolean(agentId) &&
    isCompareReady &&
    !loading &&
    leftVersionNo !== null &&
    rightVersionNo !== null &&
    leftVersionNo !== rightVersionNo;

  const configurationComparison = (
    <Spin spinning={loading}>
      {compareData?.success && versionA && versionB ? (
        (() => {
          const version_a = versionA;
          const version_b = versionB;

          const columns = [
            {
              title: t("agent.version.versionName"),
              dataIndex: "field",
              key: "field",
              width: "24%",
              className: "bg-gray-50 text-gray-600 font-medium",
            },
            {
              title: resolveVersionLabel(leftVersionNo),
              dataIndex: "current",
              key: "current",
              width: "38%",
            },
            {
              title: resolveVersionLabel(rightVersionNo),
              dataIndex: "version",
              key: "version",
              width: "38%",
            },
          ];

          const data = [
            {
              key: "name_model",
              field: (
                <Flex align="center" gap={6}>
                  <PencilLine size={14} className="text-gray-400" />
                  <span>
                    {t("agent.version.field.name")}/
                    {t("agent.version.field.modelName")}
                  </span>
                </Flex>
              ),
              current: (
                <span
                  className={
                    version_a.name !== version_b.name ||
                    JSON.stringify(version_a.model_ids || []) !==
                      JSON.stringify(version_b.model_ids || [])
                      ? "text-orange-500 font-medium"
                      : "text-gray-600"
                  }
                >
                  {version_a.name || "-"} /{" "}
                  {Array.isArray(version_a.model_names) &&
                  version_a.model_names.length > 0
                    ? version_a.model_names.join(", ")
                    : version_a.model_name || "-"}
                </span>
              ),
              version: (
                <span
                  className={
                    version_a.name !== version_b.name ||
                    JSON.stringify(version_a.model_ids || []) !==
                      JSON.stringify(version_b.model_ids || [])
                      ? "text-green-500 font-medium"
                      : "text-gray-600"
                  }
                >
                  {version_b.name || "-"} /{" "}
                  {Array.isArray(version_b.model_names) &&
                  version_b.model_names.length > 0
                    ? version_b.model_names.join(", ")
                    : version_b.model_name || "-"}
                </span>
              ),
            },
            {
              key: "description",
              field: (
                <Flex align="center" gap={6}>
                  <FileText size={14} className="text-gray-400" />
                  <span>{t("agent.version.field.description")}</span>
                </Flex>
              ),
              current: (
                <Text
                  type="secondary"
                  className={`text-xs ${
                    version_a.description !== version_b.description
                      ? "text-orange-500"
                      : ""
                  }`}
                >
                  {version_a.description || "-"}
                </Text>
              ),
              version: (
                <Text
                  type="secondary"
                  className={`text-xs ${
                    version_a.description !== version_b.description
                      ? "text-green-500"
                      : ""
                  }`}
                >
                  {version_b.description || "-"}
                </Text>
              ),
            },
            {
              key: "tools",
              field: (
                <Flex align="center" gap={6}>
                  <Wrench size={14} className="text-gray-400" />
                  <span>{t("agent.version.field.tools")}</span>
                </Flex>
              ),
              current: (
                <Tag
                  color={
                    version_a.tools?.length !== version_b.tools?.length
                      ? "orange"
                      : "default"
                  }
                >
                  {version_a.tools?.length || 0}
                </Tag>
              ),
              version: (
                <Tag
                  color={
                    version_a.tools?.length !== version_b.tools?.length
                      ? "green"
                      : "default"
                  }
                >
                  {version_b.tools?.length || 0}
                </Tag>
              ),
            },
            {
              key: "sub_agents",
              field: (
                <Flex align="center" gap={6}>
                  <Bot size={14} className="text-gray-400" />
                  <span>{t("agent.version.field.subAgents")}</span>
                </Flex>
              ),
              current: (
                <Tag
                  color={
                    version_a.sub_agent_id_list?.length !==
                    version_b.sub_agent_id_list?.length
                      ? "orange"
                      : "default"
                  }
                >
                  {version_a.sub_agent_id_list?.length || 0}
                </Tag>
              ),
              version: (
                <Tag
                  color={
                    version_a.sub_agent_id_list?.length !==
                    version_b.sub_agent_id_list?.length
                      ? "green"
                      : "default"
                  }
                >
                  {version_b.sub_agent_id_list?.length || 0}
                </Tag>
              ),
            },
          ];

          return (
            <Table
              dataSource={data}
              columns={columns}
              pagination={false}
              size="small"
              bordered
            />
          );
        })()
      ) : loading ? (
        <div className="min-h-36" />
      ) : (
        <Empty description={t("agent.version.compareFailed")} />
      )}
    </Spin>
  );

  const toConversationAgent = (
    versionNo: number | null,
    version?: AgentVersionDetail
  ): Agent => ({
    id: String(agentId),
    name: version?.name || resolveVersionLabel(versionNo),
    display_name: version?.display_name,
    description: version?.description ?? "",
    greeting_message: version?.greeting_message,
    example_questions: version?.example_questions,
    icon_url: version?.icon_url,
    model: version?.model_name ?? "",
    model_ids: version?.model_ids,
    model_names: version?.model_names,
    max_step: version?.max_steps ?? 0,
    provide_run_summary: version?.provide_run_summary ?? false,
    tools: [],
  });
  const rightAgent = toConversationAgent(rightVersionNo, versionB);
  const models = deriveModelOptions(rightAgent, availableLlmModels, "tenant");
  const selectedModelId =
    models.find(({ id }) => id === preferredModelId)?.id ??
    models.find(({ id }) =>
      rightAgent.model_ids?.some((modelId) => String(modelId) === id)
    )?.id ??
    models[0]?.id;

  const conversation = (runtime: AssistantRuntime, agent: Agent) => (
    <div className="min-h-0 flex-1 overflow-hidden px-4">
      <AssistantRuntimeProvider runtime={runtime}>
        <Thread
          agent={agent}
          chatMode={chatMode}
          debugLayout
          variant="embedded"
          showComposer={false}
          showModelSelector={false}
          showConversationTitle={false}
          readOnly
          welcomeContent={
            <AgentDebugWelcome
              agent={agent}
              disabled={!canAsk || isCompareStreaming}
              onSelectQuestion={(question) =>
                leftRuntime.thread.composer.setText(question)
              }
            />
          }
        />
      </AssistantRuntimeProvider>
    </div>
  );

  const answerComparison = (
    <div className="agent-comparison-surface h-full rounded-lg p-3">
      <TooltipProvider>
        <AgentComparisonLayout
          left={conversation(
            leftRuntime,
            toConversationAgent(leftVersionNo, versionA)
          )}
          right={conversation(rightRuntime, rightAgent)}
          footer={
            <AssistantRuntimeProvider runtime={leftRuntime}>
              <Composer
                models={models}
                selectedModelId={selectedModelId}
                onModelChange={setPreferredModelId}
                chatMode={chatMode}
                onChatModeChange={setChatMode}
                hidePlan
                disabled={!canAsk}
                submission={{
                  isRunning: isCompareStreaming,
                  send: (question) =>
                    runCompare(
                      question,
                      selectedModelId,
                      chatMode === "planning"
                    ),
                  cancel: stopCompare,
                }}
              >
                <Button
                  type="text"
                  size="small"
                  onClick={resetCompareState}
                  disabled={!canAsk || isCompareStreaming}
                >
                  {t("agent.debug.clear")}
                </Button>
              </Composer>
            </AssistantRuntimeProvider>
          }
        />
      </TooltipProvider>
    </div>
  );

  return (
    <Modal
      title={
        showRollback ? (
          <Flex align="center" gap={8}>
            <AlertTriangle className="text-orange-500" size={18} />
            {t("agent.version.rollbackCompareTitle")}
          </Flex>
        ) : (
          t("agent.version.compare")
        )
      }
      open={open}
      onCancel={handleClose}
      afterOpenChange={(visible) => {
        if (!visible) {
          setActiveTab("configuration");
        }
      }}
      footer={footer}
      width={1080}
      centered
      classNames={{
        container: "flex h-[calc(100dvh-48px)] flex-col",
        body: "flex min-h-0 flex-1 flex-col",
      }}
    >
      {onChangeVersionA && onChangeVersionB && (
        <div className="grid shrink-0 grid-cols-1 gap-3 sm:grid-cols-2">
          <Select
            aria-label={t("agent.version.compareVersionA")}
            value={leftVersionNo}
            options={versionOptions.filter(
              ({ value }) => value !== rightVersionNo
            )}
            onChange={onChangeVersionA}
            disabled={loading || isCompareStreaming || rollbackLoading}
          />
          <Select
            aria-label={t("agent.version.compareVersionB")}
            value={rightVersionNo}
            options={versionOptions.filter(
              ({ value }) => value !== leftVersionNo
            )}
            onChange={onChangeVersionB}
            disabled={loading || isCompareStreaming || rollbackLoading}
          />
        </div>
      )}
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        classNames={{
          root: "min-h-0 flex-1",
          body: "h-full",
          content: "h-full",
        }}
        items={[
          {
            key: "configuration",
            label: t("agent.version.compareBasicTitle"),
            className: "overflow-y-auto",
            children: configurationComparison,
          },
          {
            key: "answers",
            label: t("agent.version.compareQaTitle"),
            children: answerComparison,
          },
        ]}
      />
    </Modal>
  );
}
