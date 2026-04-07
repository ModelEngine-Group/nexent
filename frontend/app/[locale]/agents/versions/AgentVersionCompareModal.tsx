"use client";

import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Flex, Spin, Empty, Table, Tag, Typography, Button, Select, Input } from "antd";
import {
  AlertTriangle,
  RotateCcw,
  Cpu,
  FileText,
  MessageCircle,    
  Wrench,
  Bot,
  PencilLine
} from "lucide-react";

import type { VersionCompareResponse } from "@/services/agentVersionService";
import { conversationService } from "@/services/conversationService";
import { handleStreamResponse } from "@/app/chat/streaming/chatStreamHandler";
import { MESSAGE_ROLES } from "@/const/chatConfig";
import { ChatMessageType } from "@/types/chat";
import log from "@/lib/logger";
import DebugMessageList from "../components/agentInfo/DebugMessageList";

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
  const [compareQuestion, setCompareQuestion] = useState("");
  const [compareLeftMessages, setCompareLeftMessages] = useState<ChatMessageType[]>([]);
  const [compareRightMessages, setCompareRightMessages] = useState<ChatMessageType[]>([]);
  const [isCompareStreaming, setIsCompareStreaming] = useState(false);
  const [compareStreamingLeft, setCompareStreamingLeft] = useState(false);
  const [compareStreamingRight, setCompareStreamingRight] = useState(false);
  const compareTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const compareAbortControllersRef = useRef<{
    left: AbortController | null;
    right: AbortController | null;
  }>({ left: null, right: null });
  const compareConversationIdsRef = useRef<{
    left: number | null;
    right: number | null;
  }>({ left: null, right: null });
  const compareStepIdCountersRef = useRef<{
    left: { current: number };
    right: { current: number };
  }>({
    left: { current: 0 },
    right: { current: 0 },
  });
  const compareInFlightRef = useRef(0);

  const versionOptions =
    versionList?.map((version) => {
      const baseLabel = version.version_name || `V${version.version_no}`;
      const isCurrent = currentVersionNo !== undefined && version.version_no === currentVersionNo;
      return {
        value: version.version_no,
        label: isCurrent
          ? `${baseLabel}（${t("agent.version.currentVersion")}）`
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
    : [
        <Button key="close" type="primary" onClick={onCancel}>
          {t("common.button.close")}
        </Button>,
      ];

  const resetCompareTimeout = () => {
    if (compareTimeoutRef.current) {
      clearTimeout(compareTimeoutRef.current);
    }
    compareTimeoutRef.current = setTimeout(() => {
      setIsCompareStreaming(false);
    }, 30000);
  };

  const markCompareStopped = (
    setSideMessages: (value: (prev: ChatMessageType[]) => ChatMessageType[]) => void
  ) => {
    setSideMessages((prev) => {
      const newMessages = [...prev];
      const lastMsg = newMessages[newMessages.length - 1];
      if (lastMsg && lastMsg.role === MESSAGE_ROLES.ASSISTANT) {
        lastMsg.isComplete = true;
        lastMsg.thinking = undefined;
        lastMsg.content = t("agent.debug.stopped");
      }
      return newMessages;
    });
  };

  const handleCompareStop = async () => {
    if (compareAbortControllersRef.current.left) {
      try {
        compareAbortControllersRef.current.left.abort(t("agent.debug.userStop"));
      } catch (error) {
        log.error(t("agent.debug.cancelError"), error);
      }
    }
    if (compareAbortControllersRef.current.right) {
      try {
        compareAbortControllersRef.current.right.abort(t("agent.debug.userStop"));
      } catch (error) {
        log.error(t("agent.debug.cancelError"), error);
      }
    }

    compareAbortControllersRef.current = { left: null, right: null };

    if (compareTimeoutRef.current) {
      clearTimeout(compareTimeoutRef.current);
      compareTimeoutRef.current = null;
    }

    setIsCompareStreaming(false);
    setCompareStreamingLeft(false);
    setCompareStreamingRight(false);
    markCompareStopped(setCompareLeftMessages);
    markCompareStopped(setCompareRightMessages);

    const { left, right } = compareConversationIdsRef.current;
    compareConversationIdsRef.current = { left: null, right: null };

    if (left != null) {
      try {
        await conversationService.stop(left);
      } catch (error) {
        log.error(t("agent.debug.stopError"), error);
      }
    }
    if (right != null) {
      try {
        await conversationService.stop(right);
      } catch (error) {
        log.error(t("agent.debug.stopError"), error);
      }
    }
  };

  const resetCompareState = () => {
    setCompareQuestion("");
    setCompareLeftMessages([]);
    setCompareRightMessages([]);
    compareStepIdCountersRef.current.left.current = 0;
    compareStepIdCountersRef.current.right.current = 0;
    setIsCompareStreaming(false);
    setCompareStreamingLeft(false);
    setCompareStreamingRight(false);
  };

  useEffect(() => {
    if (!open) {
      handleCompareStop();
      resetCompareState();
      return;
    }
    resetCompareState();
  }, [open]);

  useEffect(() => {
    if (isCompareStreaming) {
      handleCompareStop();
    }
    resetCompareState();
  }, [selectedVersionNoA, selectedVersionNoB]);

  const runCompareStream = async (params: {
    versionNo: number;
    conversationId: number;
    controller: AbortController;
    setSideMessages: Dispatch<SetStateAction<ChatMessageType[]>>;
    stepIdCounterRef: { current: number };
    question: string;
    agentIdValue: number;
    onStreamEnd: () => void;
  }) => {
    try {
      const reader = await conversationService.runAgent(
        {
          query: params.question,
          conversation_id: params.conversationId,
          is_set: true,
          history: [],
          is_debug: true,
          agent_id: params.agentIdValue,
          version_no: params.versionNo,
        },
        params.controller.signal
      );

      if (!reader) throw new Error(t("agent.debug.nullResponse"));

      await handleStreamResponse(
        reader,
        params.setSideMessages,
        resetCompareTimeout,
        params.stepIdCounterRef,
        () => {},
        false,
        () => {},
        async () => {},
        params.conversationId,
        conversationService,
        true,
        t
      );
    } catch (error) {
      const err = error as Error;
      if (err.name === "AbortError") {
        markCompareStopped(params.setSideMessages);
      } else {
        log.error(t("agent.debug.streamError"), error);
        const errorMessage =
          error instanceof Error
            ? error.message
            : t("agent.debug.processError");
        params.setSideMessages((prev) => {
          const newMessages = [...prev];
          const lastMsg = newMessages[newMessages.length - 1];
          if (lastMsg && lastMsg.role === MESSAGE_ROLES.ASSISTANT) {
            lastMsg.content = errorMessage;
            lastMsg.isComplete = true;
            lastMsg.error = errorMessage;
          }
          return newMessages;
        });
      }
    } finally {
      compareInFlightRef.current -= 1;
      if (compareInFlightRef.current <= 0) {
        setIsCompareStreaming(false);
      }
      params.onStreamEnd();
    }
  };

  const resolveVersionLabel = (versionNo: number | null | undefined) => {
    if (!versionNo) return "-";
    const matched = versionList?.find((v) => v.version_no === versionNo);
    return matched?.version_name || `V${versionNo}`;
  };

  const resolveVersionModel = (versionNo: number | null | undefined) => {
    if (!versionNo || !compareData?.data) return "-";
    const { version_a, version_b } = compareData.data;
    if (version_a?.version?.version_no === versionNo) {
      return version_a.model_name || "-";
    }
    if (version_b?.version?.version_no === versionNo) {
      return version_b.model_name || "-";
    }
    return "-";
  };

  const handleCompareAsk = async () => {
    if (!agentId) return;
    const question = compareQuestion.trim();
    if (!question) return;

    const versionNoA = selectedVersionNoA ?? compareData?.data?.version_a?.version?.version_no;
    const versionNoB = selectedVersionNoB ?? compareData?.data?.version_b?.version?.version_no;
    if (!versionNoA || !versionNoB) return;
    if (versionNoA === versionNoB) return;

    setIsCompareStreaming(true);
    setCompareStreamingLeft(true);
    setCompareStreamingRight(true);
    compareInFlightRef.current = 2;
    compareStepIdCountersRef.current.left.current = 0;
    compareStepIdCountersRef.current.right.current = 0;

    const leftUserMessage: ChatMessageType = {
      id: `${Date.now()}-left-user`,
      role: MESSAGE_ROLES.USER,
      content: question,
      timestamp: new Date(),
    };
    const rightUserMessage: ChatMessageType = {
      id: `${Date.now()}-right-user`,
      role: MESSAGE_ROLES.USER,
      content: question,
      timestamp: new Date(),
    };

    const leftAssistantMessage: ChatMessageType = {
      id: `${Date.now()}-left-assistant`,
      role: MESSAGE_ROLES.ASSISTANT,
      content: "",
      timestamp: new Date(),
      isComplete: false,
    };
    const rightAssistantMessage: ChatMessageType = {
      id: `${Date.now()}-right-assistant`,
      role: MESSAGE_ROLES.ASSISTANT,
      content: "",
      timestamp: new Date(),
      isComplete: false,
    };

    setCompareLeftMessages([leftUserMessage, leftAssistantMessage]);
    setCompareRightMessages([rightUserMessage, rightAssistantMessage]);

    const baseId = -Math.abs(Date.now());
    const leftConversationId = baseId;
    const rightConversationId = baseId - 1;
    compareConversationIdsRef.current = {
      left: leftConversationId,
      right: rightConversationId,
    };

    const leftController = new AbortController();
    const rightController = new AbortController();
    compareAbortControllersRef.current = {
      left: leftController,
      right: rightController,
    };

    await Promise.allSettled([
      runCompareStream({
        versionNo: versionNoA,
        conversationId: leftConversationId,
        controller: leftController,
        setSideMessages: setCompareLeftMessages,
        stepIdCounterRef: compareStepIdCountersRef.current.left,
        question,
        agentIdValue: agentId,
        onStreamEnd: () => setCompareStreamingLeft(false),
      }),
      runCompareStream({
        versionNo: versionNoB,
        conversationId: rightConversationId,
        controller: rightController,
        setSideMessages: setCompareRightMessages,
        stepIdCounterRef: compareStepIdCountersRef.current.right,
        question,
        agentIdValue: agentId,
        onStreamEnd: () => setCompareStreamingRight(false),
      }),
    ]);

    compareAbortControllersRef.current = { left: null, right: null };
    if (compareTimeoutRef.current) {
      clearTimeout(compareTimeoutRef.current);
      compareTimeoutRef.current = null;
    }
  };

  return (
    <Modal
      title={
        <Flex align="center" gap={8}>
          <AlertTriangle className="text-orange-500" size={18} />
          <span>
            {showRollback
              ? t("agent.version.rollbackCompareTitle")
              : t("agent.version.compare")}
          </span>
        </Flex>
      }
      open={open}
      onCancel={onCancel}
      footer={footer}
      width={800}
      centered
    >
      <Spin spinning={loading}>
        {compareData?.success && compareData?.data ? (
          <Flex vertical gap={16}>
            {(() => {
              const { version_a, version_b } = compareData.data;

              const columns = [
                {
                  title: t("agent.version.versionName"),
                  dataIndex: "field",
                  key: "field",
                  width: "25%",
                  className: "bg-gray-50 text-gray-600 font-medium",
                },
                {
                  title:
                    versionOptions && onChangeVersionA ? (
                      <Select
                        style={{ minWidth: 140 }}
                        size="small"
                        value={selectedVersionNoA ?? version_a.version.version_no}
                        options={versionOptions}
                        onChange={onChangeVersionA}
                      />
                    ) : (
                      version_a.version.version_name
                    ),
                  dataIndex: "current",
                  key: "current",
                  width: "37%",
                },
                {
                  title:
                    versionOptions && onChangeVersionB ? (
                      <Select
                        style={{ minWidth: 140 }}
                        size="small"
                        value={selectedVersionNoB ?? version_b.version.version_no}
                        options={versionOptions}
                        onChange={onChangeVersionB}
                      />
                    ) : (
                      version_b.version.version_name
                    ),
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
                        {t("agent.version.field.name")}/{t("agent.version.field.modelName")}
                      </span>
                    </Flex>
                  ),
                  current: (
                    <span
                      className={
                        version_a.name !== version_b.name ||
                        version_a.model_name !== version_b.model_name
                          ? "text-orange-500 font-medium"
                          : "text-gray-600"
                      }
                    >
                      {version_a.name || "-"} / {version_a.model_name || "-"}
                    </span>
                  ),
                  version: (
                    <span
                      className={
                        version_a.name !== version_b.name ||
                        version_a.model_name !== version_b.model_name
                          ? "text-green-500 font-medium"
                          : "text-gray-600"
                      }
                    >
                      {version_b.name || "-"} / {version_b.model_name || "-"}
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
            })()}
            <div className="flex flex-col gap-3">
              <div className="text-sm font-medium">
                {t("agent.version.compareQaTitle")}
              </div>
              <Input.TextArea
                value={compareQuestion}
                onChange={(e) => setCompareQuestion(e.target.value)}
                placeholder={t("agent.version.compareQaPlaceholder")}
                autoSize={{ minRows: 2, maxRows: 4 }}
                disabled={isCompareStreaming}
                onPressEnter={(e) => {
                  if (!e.shiftKey) {
                    e.preventDefault();
                    handleCompareAsk();
                  }
                }}
              />
              <Flex align="center" justify="space-between">
                <div className="text-xs text-gray-500">
                  {t("agent.version.compareQaHint")}
                </div>
                <Flex gap={8}>
                  {isCompareStreaming && (
                    <Button danger onClick={handleCompareStop}>
                      {t("agent.debug.stop")}
                    </Button>
                  )}
                  <Button
                    type="primary"
                    onClick={handleCompareAsk}
                    disabled={isCompareStreaming}
                  >
                    {t("agent.version.compareQaRun")}
                  </Button>
                </Flex>
              </Flex>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="flex flex-col min-h-0 border border-gray-200 rounded-md p-3 overflow-hidden">
                  <div className="text-xs text-gray-500 mb-2">
                    {resolveVersionLabel(selectedVersionNoA ?? version_a.version.version_no)} ·{" "}
                    {resolveVersionModel(selectedVersionNoA ?? version_a.version.version_no)}
                  </div>
                  <DebugMessageList
                    messages={compareLeftMessages}
                    isStreaming={compareStreamingLeft}
                    emptyPlaceholder={t("agent.version.compareQaEmpty")}
                  />
                </div>
                <div className="flex flex-col min-h-0 border border-gray-200 rounded-md p-3 overflow-hidden">
                  <div className="text-xs text-gray-500 mb-2">
                    {resolveVersionLabel(selectedVersionNoB ?? version_b.version.version_no)} ·{" "}
                    {resolveVersionModel(selectedVersionNoB ?? version_b.version.version_no)}
                  </div>
                  <DebugMessageList
                    messages={compareRightMessages}
                    isStreaming={compareStreamingRight}
                    emptyPlaceholder={t("agent.version.compareQaEmpty")}
                  />
                </div>
              </div>
            </div>
          </Flex>
        ) : (
          <Empty description={t("agent.version.compareFailed")} />
        )}
      </Spin>
    </Modal>
  );
}

