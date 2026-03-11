"use client";

import { useTranslation } from "react-i18next";
import { Modal, Flex, Spin, Empty, Table, Tag, Typography, Button, Select } from "antd";
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

const { Text } = Typography;

export interface AgentVersionCompareModalProps {
  open: boolean;
  loading: boolean;
  compareData: VersionCompareResponse | null;
  onCancel: () => void;
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
                  key: "name",
                  field: (
                    <Flex align="center" gap={6}>
                      <PencilLine size={14} className="text-gray-400" />
                      <span>{t("agent.version.field.name")}</span>
                    </Flex>
                  ),
                  current: (
                    <span
                      className={
                        version_a.name !== version_b.name
                          ? "text-orange-500 font-medium"
                          : "text-gray-600"
                      }
                    >
                      {version_a.name}
                    </span>
                  ),
                  version: (
                    <span
                      className={
                        version_a.name !== version_b.name
                          ? "text-green-500 font-medium"
                          : "text-gray-600"
                      }
                    >
                      {version_b.name}
                    </span>
                  ),
                },
                {
                  key: "model_name",
                  field: (
                    <Flex align="center" gap={6}>
                      <Cpu size={14} className="text-gray-400" />
                      <span>{t("agent.version.field.modelName")}</span>
                    </Flex>
                  ),
                  current: (
                    <span
                      className={
                        version_a.model_name !== version_b.model_name
                          ? "text-orange-500 font-medium"
                          : "text-gray-600"
                      }
                    >
                      {version_a.model_name || "-"}
                    </span>
                  ),
                  version: (
                    <span
                      className={
                        version_a.model_name !== version_b.model_name
                          ? "text-green-500 font-medium"
                          : "text-gray-600"
                      }
                    >
                      {version_b.model_name || "-"}
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
                  key: "duty_prompt",
                  field: (
                    <Flex align="center" gap={6}>
                      <MessageCircle size={14} className="text-gray-400" />
                      <span>{t("agent.version.field.dutyPrompt")}</span>
                    </Flex>
                  ),
                  current: (
                    <Text
                      type="secondary"
                      className={`text-xs ${
                        version_a.duty_prompt !== version_b.duty_prompt
                          ? "text-orange-500"
                          : ""
                      }`}
                    >
                      {version_a.duty_prompt?.slice(0, 100) || "-"}
                      {version_a.duty_prompt &&
                        version_a.duty_prompt.length > 100 &&
                        "..."}
                    </Text>
                  ),
                  version: (
                    <Text
                      type="secondary"
                      className={`text-xs ${
                        version_a.duty_prompt !== version_b.duty_prompt
                          ? "text-green-500"
                          : ""
                      }`}
                    >
                      {version_b.duty_prompt?.slice(0, 100) || "-"}
                      {version_b.duty_prompt &&
                        version_b.duty_prompt.length > 100 &&
                        "..."}
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
          </Flex>
        ) : (
          <Empty description={t("agent.version.compareFailed")} />
        )}
      </Spin>
    </Modal>
  );
}

