"use client";
import { useMemo, useState } from "react";
import {
  CheckCircle,
  Archive,
  Clock,
  ChevronDown,
  ChevronRight,
  Rocket,
  RotateCcw,
  Eye,
  Wrench,
  Network,
  AlertTriangle,
  EllipsisVertical,
  Trash2,
  ArchiveRestore
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  Flex,
  Button,
  Tag,
  Typography,
  Card,
  Descriptions,
  DescriptionsProps,
  Modal,
  Dropdown,
  theme
} from "antd";
import { ExclamationCircleFilled } from '@ant-design/icons';

const { useToken } = theme;
import type { AgentVersion, Agent as AgentVersionAgent, ToolInstance, AgentVersionDetail, VersionCompareResponse } from "@/services/agentVersionService";
import type { Agent, Tool } from "@/types/agentConfig";
import { useToolList } from "@/hooks/agent/useToolList";
import { useAgentList } from "@/hooks/agent/useAgentList";
import { useAgentVersionList } from "@/hooks/agent/useAgentVersionList";
import { useAgentInfo } from "@/hooks/agent/useAgentInfo";
import { useAgentVersionDetail } from "@/hooks/agent/useAgentVersionDetail";
import { rollbackVersion, compareVersions, deleteVersion } from "@/services/agentVersionService";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import log from "@/lib/logger";
import { message } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import AgentVersionCompareModal from "./versions/AgentVersionCompareModal";

const { Text } = Typography;

const formatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

/**
 * Format UTC time string from backend to local time string based on user timezone
 */
function formatUtcToLocal(dateTimeStr?: string | null) {
  if (!dateTimeStr) {
    return "";
  }

  // Detect whether the string already contains timezone information
  const hasTimezone = /[zZ]|[+\-]\d{2}:?\d{2}$/.test(dateTimeStr);

  let date: Date;
  if (hasTimezone) {
    // If timezone exists, use as is
    date = new Date(dateTimeStr);
  } else {
    // Treat as UTC time from database, convert to local time
    // Normalize space-separated format like "2025-02-25 08:00:00"
    const normalized = dateTimeStr.replace(" ", "T");
    date = new Date(`${normalized}Z`);
  }

  return formatter.format(date);
}

/**
 * Get status configuration based on isCurrentVersion flag
 */
function getStatusConfig(isCurrentVersion: boolean) {
  if (isCurrentVersion) {
    return {
      color: "green",
      icon: (
        <div className="w-8 h-8 rounded-full bg-green-50 flex items-center justify-center">
          <CheckCircle className="text-green-500" size={16} />
        </div>
      ),
      labelKey: "agent.version.currentVersion",
    };
  }

  return {
    color: "default",
    icon: (
      <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center">
        <Archive className="text-gray-400" size={16} />
      </div>
    ),
    labelKey: "",
  };
}

/**
 * Version card item component
 */
export function VersionCardItem({
  version,
  agentId,
  currentVersionNo,
}: {
  version: AgentVersion;
  agentId: number;
  currentVersionNo?: number;
}) {
  // Calculate isCurrentVersion based on version.version_no and currentVersionNo
  const isCurrentVersion = currentVersionNo === version.version_no;
  const statusConfig = getStatusConfig(isCurrentVersion);
  const { t } = useTranslation("common");

  // Local expanded state for this version card
  const [isExpanded, setIsExpanded] = useState(false);

  // Get user context for tenantId
  const { user } = useAuthorizationContext();
  const queryClient = useQueryClient();

  // Get invalidate functions for refreshing data
  const { agentVersionList, invalidate: invalidateAgentVersionList } = useAgentVersionList(agentId);
  const { invalidate: invalidateAgentInfo } = useAgentInfo(agentId);

  // Fetch version detail when expanded
  const { agentVersionDetail } = useAgentVersionDetail(
    agentId,
    isExpanded ? version.version_no : null
  );

  const { tools: toolList } = useToolList();
  const { agents: agentList } = useAgentList(user?.tenantId ?? null);

  // Modal state
  const [compareModalOpen, setCompareModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [rollbackLoading, setRollbackLoading] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [compareData, setCompareData] = useState<VersionCompareResponse | null>(null);
  const [selectedVersionNoA, setSelectedVersionNoA] = useState<number | null>(null);
  const [selectedVersionNoB, setSelectedVersionNoB] = useState<number | null>(null);

  // Get theme token for styling
  const { token } = theme.useToken();

  // Generate display date from version data (convert from UTC to local time)
  const displayDate = useMemo(() => {
    return formatUtcToLocal(version.create_time);
  }, [version.create_time]);

  /**
   * Handle rollback button click - show comparison modal
   */
  const handleRollbackClick = async () => {
    if (!agentId || agentId === 0) {
      message.error(t("agent.error.agentNotFound"));
      return;
    }
    const versionNoA = currentVersionNo || 0;
    const versionNoB = version.version_no;
    setSelectedVersionNoA(versionNoA);
    setSelectedVersionNoB(versionNoB);
    setCompareModalOpen(true);
    await loadComparison(versionNoA, versionNoB);
  };

  /**
   * Load version comparison data between current version and selected version
   */
  const loadComparison = async (versionNoA: number, versionNoB: number) => {
    setLoading(true);
    try {
      const result = await compareVersions(agentId, versionNoA, versionNoB);
      setCompareData(result);
    } catch (error) {
      log.error("Failed to load version comparison:", error);
      message.error(t("agent.version.compareError"));
    } finally {
      setLoading(false);
    }
  };

  const handleChangeVersionA = async (value: number) => {
    setSelectedVersionNoA(value);
    if (!selectedVersionNoB) {
      return;
    }
    if (value === selectedVersionNoB) {
      message.warning(t("agent.version.selectDifferentVersions"));
      return;
    }
    await loadComparison(value, selectedVersionNoB);
  };

  const handleChangeVersionB = async (value: number) => {
    setSelectedVersionNoB(value);
    if (!selectedVersionNoA) {
      return;
    }
    if (value === selectedVersionNoA) {
      message.warning(t("agent.version.selectDifferentVersions"));
      return;
    }
    await loadComparison(selectedVersionNoA, value);
  };

  /**
   * Handle rollback confirmation
   * Rollback updates current_version_no to point to the target version
   * The user can then click publish to create an actual new version
   */
  const handleRollbackConfirm = async () => {
    setRollbackLoading(true);
    try {
      const result = await rollbackVersion(agentId, version.version_no);

      if (result.success) {
        message.success(t("agent.version.rollbackSuccess"));
        setCompareModalOpen(false);
        invalidateAgentVersionList?.();
        invalidateAgentInfo?.();
        queryClient.invalidateQueries({ queryKey: ["agents"] });
      } else {
        message.error(result.message || t("agent.version.rollbackError"));
      }
    } catch (error) {
      log.error("Failed to rollback version:", error);
      message.error(t("agent.version.rollbackError"));
    } finally {
      setRollbackLoading(false);
    }
  };

  /**
   * Handle delete version button click - show confirmation modal
   */
  const handleDeleteClick = () => {
    if (!agentId || agentId === 0) {
      message.error(t("agent.error.agentNotFound"));
      return;
    }
    setDeleteModalOpen(true);
  };

  /**
   * Handle delete confirmation - actually delete the version
   */
  const handleDeleteConfirm = async () => {
    setDeleteLoading(true);
    try {
      const result = await deleteVersion(agentId, version.version_no);

      if (result.success) {
        message.success(t("agent.version.deleteSuccess"));
        setDeleteModalOpen(false);
        invalidateAgentVersionList?.();
        invalidateAgentInfo?.();
        queryClient.invalidateQueries({ queryKey: ["agents"] });
      } else {
        message.error(result.message || t("agent.version.deleteError"));
      }
    } catch (error) {
      log.error("Failed to delete version:", error);
      message.error(t("agent.version.deleteError"));
    } finally {
      setDeleteLoading(false);
    }
  };

  const agentConfigurationItems: DescriptionsProps['items'] = [
    {
      key: '1',
      label: t("agent.version.field.name"),
      children: <span>{agentVersionDetail?.name}</span>,
    },
    {
      key: '2',
      label: t("agent.version.field.modelName"),
      children: <span>{agentVersionDetail?.model_name}</span>,
    },
  ];

  return (
    <div className="pb-6 last:pb-0">
      <Card
        className={`w-full transition-all duration-200 ${isExpanded ? "ring-2 ring-blue-100" : ""} ${isCurrentVersion ? "border border-green-400" : ""}`}
        styles={{ body: { padding: "12px 16px" } }}
        size="small"
      >
        <Flex className="h-full" gap={12}>
          {/* Left: Status icon with timeline */}
          <Flex align="center" justify="center" vertical className="flex-shrink-0">
            <Flex align="center" justify="center" className="flex-shrink-0">
              {statusConfig.icon}
            </Flex>
            <div className="w-px h-full bg-gray-200" />
          </Flex>

          {/* Middle: Version info */}
          <Flex
            vertical
            gap={4}
            className="flex-1 min-w-0"
          >
            <Flex align="center" gap={8}>
              <Text strong className="text-base">
                {version.version_name || `V${version.version_no}`}
              </Text>
              <Tag color={statusConfig.color} className="m-0">
                {t(statusConfig.labelKey)}
              </Tag>
            </Flex>

            <Flex align="center" gap={12} className="text-gray-500 text-xs">
              <Flex align="center" gap={4}>
                <Clock size={12} />
                <Text type="secondary" className="text-xs">
                  {displayDate}
                </Text>
              </Flex>

            </Flex>

            {version.release_note && (
              <Text
                type="secondary"
                className="text-sm mt-1 line-clamp-2"
                ellipsis={{ tooltip: version.release_note }}
              >
                {version.release_note}
              </Text>
            )}
          </Flex>

          {/* Right: Actions */}
          <Flex align="start" justify="center" gap={8} className="flex-shrink-0">
            <Button
              type="text"
              size="small"
              icon={isExpanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
              onClick={() => setIsExpanded(!isExpanded)}
              className="text-gray-400 hover:text-gray-600"
            />
            <Dropdown
              menu={{
                items: [
                  {
                    key: 'rollback',
                    label: t("agent.version.rollback"),
                    icon: <RotateCcw size={14} />,
                    disabled: isCurrentVersion || version.status.toLowerCase() === "disabled",
                    onClick: handleRollbackClick
                  },
                  {
                    type: 'divider',
                  },
                  {
                    key: 'delete',
                    label: t("common.delete"),
                    icon: <Trash2 size={14} />,
                    disabled: isCurrentVersion,
                    danger: true,
                    onClick: handleDeleteClick,
                  },
                ],
              }}
              trigger={['click']}
            >
              <Button
                type="text"
                size="small"
                icon={<EllipsisVertical size={18} />}
                className="text-gray-400 hover:text-gray-600"
              />
            </Dropdown>
          </Flex>

        </Flex>

        {/* Expanded content */}
        {isExpanded && (
          <div className="mt-4 pt-4 border-t border-gray-100">
            <Flex vertical gap={16}>

              <Descriptions
                title={
                  <Flex align="center" gap={8}>
                    <Eye size={14} className="text-blue-500" />
                    <span className="text-sm">{t("agent.version.configuration")}</span>
                  </Flex>
                }
                items={agentConfigurationItems}
                classNames={{ header: "!mb-2" }}
                column={1}
                className="[&_.ant-descriptions-item]:!pb-0"
              />

              {/* Tools detail */}
              {agentVersionDetail?.tools && agentVersionDetail.tools.length > 0 && (
                <Descriptions
                  title={
                    <Flex align="center" gap={8}>
                      <Wrench size={14} className="text-blue-500" />
                      <span className="text-sm">{t("agent.version.tools")}</span>
                    </Flex>
                  }
                  items={[
                    {
                      key: '1',
                      children: (
                        <Flex wrap gap={6}>
                          {agentVersionDetail.tools.map((tool) => {
                            const fullTool = toolList.find((t: Tool) => t.id === String(tool.tool_id));
                            return (
                              <Tag key={tool.tool_id} color="blue">
                                {fullTool?.name}
                              </Tag>
                            );
                          })}
                        </Flex>
                      ),
                    },
                  ]}
                  classNames={{ header: "!mb-2" }}
                  className="[&_.ant-descriptions-item]:!pb-0"
                />
              )}


              {/* Related agents detail */}
              {agentVersionDetail?.sub_agent_id_list && agentVersionDetail.sub_agent_id_list.length > 0 && (
                <Descriptions
                  title={
                    <Flex align="center" gap={8}>
                      <Network size={14} className="text-blue-500" />
                      <span className="text-sm">{t("agent.version.relatedAgents")}</span>
                    </Flex>
                  }
                  items={[
                    {
                      key: '1',
                      children: (
                        <Flex wrap gap={6}>
                          {agentVersionDetail.sub_agent_id_list.map((subAgentId) => {
                            const subAgent = agentList.find((a: Agent) => a.id === String(subAgentId));
                            return (
                              <Tag key={subAgentId} color="purple">
                                {subAgent?.display_name || subAgent?.name || `Agent ${subAgentId}`}
                              </Tag>
                            );
                          })}
                        </Flex>
                      ),
                    },
                  ]}
                  classNames={{ header: "!mb-2" }}
                  className="[&_.ant-descriptions-item]:!pb-0"
                />
              )}
            </Flex>
          </div>
        )}
      </Card>

      <AgentVersionCompareModal
        open={compareModalOpen}
        loading={loading}
        versionList={agentVersionList || []}
        currentVersionNo={currentVersionNo}
        compareData={compareData}
        onCancel={() => setCompareModalOpen(false)}
        showRollback
        rollbackLoading={rollbackLoading}
        onRollbackConfirm={handleRollbackConfirm}
        selectedVersionNoA={selectedVersionNoA}
        selectedVersionNoB={selectedVersionNoB}
        onChangeVersionA={handleChangeVersionA}
        onChangeVersionB={handleChangeVersionB}
      />

      {/* Delete Version Confirmation Modal */}
      <Modal
        title={t("agent.version.deleteConfirmTitle")}
        open={deleteModalOpen}
        onCancel={() => setDeleteModalOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setDeleteModalOpen(false)}>
            {t("common.cancel")}
          </Button>,
          <Button
            key="confirm"
            type="primary"
            danger
            icon={<Trash2 size={14} />}
            loading={deleteLoading}
            onClick={handleDeleteConfirm}
          >
            {t("common.delete")}
          </Button>,
        ]}
        centered
      >
        <Flex align="start" gap={12}>
          <div className="mt-1">
            <ExclamationCircleFilled style={{ color: token.colorWarning, fontSize: '22px' }} />
          </div>
          <div>
            <div className="font-medium mb-2">
              {t("agent.version.deleteConfirmContent", { versionName: version.version_name || `V${version.version_no}` })}
            </div>
            <div className="text-sm text-gray-500">
              {t("agent.version.deleteWarning")}
            </div>
          </div>
        </Flex>
      </Modal>
    </div>
  );
}
