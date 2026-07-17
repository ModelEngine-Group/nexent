"use client";

import React, { useMemo, useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import {
  Table,
  Popconfirm,
  message,
  Button,
  Modal,
  Tag,
  Tooltip,
  InputNumber,
  Progress,
  Space,
  Segmented,
} from "antd";
import { ColumnsType } from "antd/es/table";
import { Edit, Trash2, BookOpen } from "lucide-react";
import { SettingOutlined } from "@ant-design/icons";
import {
  emitQuotaUsageChanged,
  QUOTA_USAGE_CHANGED_EVENT,
} from "@/lib/quotaEvents";
import { MarkdownRenderer } from "@/components/common/markdownRenderer";
import { useKnowledgeList } from "@/hooks/knowledge/useKnowledgeList";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorization } from "@/hooks/auth/useAuthorization";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import quotaService from "@/services/quotaService";
import { type KnowledgeBase } from "@/types/knowledgeBase";
import type { QuotaUsageResponse, KBQuotaStatus } from "@/types/quota";
import { KnowledgeBaseEditModal } from "../../../knowledges/components/knowledge/KnowledgeBaseEditModal";
import { QuotaSettingsModal } from "./QuotaSettingsModal";
import { SuQuotaModal } from "./SuQuotaModal";

// Color constants for progress bars
const STROKE_COLORS = {
  normal: "#52c41a",
  warning: "#faad14",
  critical: "#ff4d4f",
  exceeded: "#d48806",
  blocked: "#ff4d4f",
};

type ProgressWarningLevel =
  | KBQuotaStatus["kb_warning_level"]
  | QuotaUsageResponse["tenant_warning_level"];

function getProgressColor(level: ProgressWarningLevel | null | undefined): string {
  return level ? STROKE_COLORS[level] : STROKE_COLORS.normal;
}

export default function KnowledgeList({
  tenantId,
}: {
  tenantId: string | null;
}) {
  const { t } = useTranslation("common");
  const { data, isLoading, refetch } = useKnowledgeList(tenantId);
  const knowledgeBases = data || [];

  // Get actual user role from auth context
  const { user } = useAuthorization();
  const userRole = user?.role ?? "";
  // Only ADMIN can edit per-KB soft quotas
  const isAdmin = userRole === "ADMIN";
  // SU and ADMIN can both manage tenant hard limit
  const canManageQuota = userRole === "ADMIN" || userRole === "SU";

  // Fetch groups for group selection
  const { data: groupData } = useGroupList(tenantId);
  const groups = groupData?.groups || [];

  // Quota state
  const [quotaUsage, setQuotaUsage] = useState<QuotaUsageResponse | null>(null);
  const [quotaModalVisible, setQuotaModalVisible] = useState(false);
  const [editingQuotaKb, setEditingQuotaKb] = useState<string | null>(null);
  const [editingQuotaValue, setEditingQuotaValue] = useState<number | null>(
    null
  );
  const [editingQuotaUnit, setEditingQuotaUnit] = useState<"GB" | "MB">("GB");
  const [savingQuota, setSavingQuota] = useState(false);

  const [editingKnowledge, setEditingKnowledge] =
    useState<KnowledgeBase | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [summaryModalVisible, setSummaryModalVisible] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryContent, setSummaryContent] = useState<string>("");

  // Fetch quota usage
  const fetchQuotaUsage = useCallback(async () => {
    if (!tenantId) return;
    try {
      const usage = await quotaService.getQuotaUsage(tenantId, true, true);
      setQuotaUsage(usage);
    } catch (err: any) {
      // Quota API may not be available if no quota is configured — silent
      if (err.code !== 404) {
        console.warn("Failed to fetch quota usage:", err.message);
      }
    }
  }, [tenantId]);

  const handleQuotaUsageChange = useCallback((usage: QuotaUsageResponse) => {
    setQuotaUsage(usage);
  }, []);

  useEffect(() => {
    if (canManageQuota) {
      fetchQuotaUsage();
    }
  }, [fetchQuotaUsage, canManageQuota]);

  useEffect(() => {
    window.addEventListener(QUOTA_USAGE_CHANGED_EVENT, fetchQuotaUsage);
    return () => {
      window.removeEventListener(QUOTA_USAGE_CHANGED_EVENT, fetchQuotaUsage);
    };
  }, [fetchQuotaUsage]);

  // Refetch quota after KnowledgeBase list changes
  const handleRefetch = useCallback(() => {
    refetch();
    fetchQuotaUsage();
  }, [refetch, fetchQuotaUsage]);

  // Build quota lookup map: index_name -> KBQuotaStatus
  const quotaMap = useMemo(() => {
    const map = new Map<string, KBQuotaStatus>();
    if (quotaUsage?.breakdown) {
      for (const kb of quotaUsage.breakdown) {
        map.set(kb.index_name, kb);
      }
    }
    return map;
  }, [quotaUsage]);

  // Build KB id lookup: index_name -> knowledge_id
  const kbIdMap = useMemo(() => {
    const map = new Map<string, number>();
    for (const kb of knowledgeBases) {
      if (kb.index_name) {
        map.set(kb.index_name, kb.id as unknown as number);
      }
    }
    return map;
  }, [knowledgeBases]);

  // Create group name mapping
  const groupNameMap = useMemo(() => {
    const map = new Map<number, string>();
    groups.forEach((group) => {
      map.set(group.group_id, group.group_name);
    });
    return map;
  }, [groups]);

  // Get group names for knowledge base
  const getGroupNames = (groupIds?: number[]) => {
    if (!groupIds || groupIds.length === 0) return [];
    return groupIds
      .map((id) => groupNameMap.get(id) || `Group ${id}`)
      .filter(Boolean);
  };

  const handleDelete = async (knowledgeId: string) => {
    try {
      await knowledgeBaseService.deleteKnowledgeBase(knowledgeId);
      message.success(t("tenantResources.knowledgeBase.deleted"));
      handleRefetch();
    } catch (error: any) {
      message.error(
        error.message || t("tenantResources.knowledgeBase.deleteFailed")
      );
    }
  };

  const openEdit = (knowledge: KnowledgeBase) => {
    setEditingKnowledge(knowledge);
    setModalVisible(true);
  };

  const openEditSummary = async (knowledge: KnowledgeBase) => {
    setEditingKnowledge(knowledge);
    setSummaryLoading(true);
    setSummaryContent("");
    try {
      const summary = await knowledgeBaseService.getSummary(knowledge.id);
      setSummaryContent(summary || "");
      setSummaryModalVisible(true);
    } catch (error: any) {
      message.error(
        error.message || t("tenantResources.knowledgeBase.getSummaryFailed")
      );
    } finally {
      setSummaryLoading(false);
    }
  };

  const formatDateTime = (date: string | null | undefined) => {
    if (!date) return t("common.unknown");
    const d = new Date(date);
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    const hours = String(d.getHours()).padStart(2, "0");
    const minutes = String(d.getMinutes()).padStart(2, "0");
    const seconds = String(d.getSeconds()).padStart(2, "0");
    return `${year}/${month}/${day} ${hours}:${minutes}:${seconds}`;
  };

  // Inline editing for per-KB quota
  const GB = 1024 * 1024 * 1024;
  const MB = 1024 * 1024;

  const startEditQuota = (indexName: string, currentBytes: number | null) => {
    setEditingQuotaKb(indexName);
    if (currentBytes && currentBytes < GB) {
      setEditingQuotaUnit("MB");
      setEditingQuotaValue(Math.round(currentBytes / MB));
    } else {
      setEditingQuotaUnit("GB");
      setEditingQuotaValue(currentBytes ? Math.round(currentBytes / GB) : null);
    }
  };

  const saveQuotaEdit = async (indexName: string) => {
    if (!tenantId) return;
    setSavingQuota(true);
    try {
      const limitBytes =
        editingQuotaValue != null
          ? editingQuotaValue * (editingQuotaUnit === "MB" ? MB : GB)
          : null;
      // Use PATCH endpoint on the knowledge base
      const response = await fetch(`/api/indices/${indexName}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ quota_limit_bytes: limitBytes }),
      });
      if (!response.ok) {
        throw new Error("Failed to update quota");
      }
      emitQuotaUsageChanged();
      message.success(t("quota.saveSuccess", "Quota updated"));
      setEditingQuotaKb(null);
      fetchQuotaUsage();
    } catch (err: any) {
      message.error(err.message || "Failed to update quota");
    } finally {
      setSavingQuota(false);
    }
  };

  const cancelQuotaEdit = () => {
    setEditingQuotaKb(null);
    setEditingQuotaValue(null);
  };

  // Check if knowledge base is from external source (not Nexent)
  const isExternalSource = (record: KnowledgeBase) => {
    const source = record.source || record.knowledge_sources;
    return source && source !== "nexent" && source !== "elasticsearch";
  };

  // Tenant-level usage info for overview bar
  const tenantUsagePct = quotaUsage?.usage_pct ?? null;
  const tenantTotalReadable = quotaUsage?.total_readable;
  const tenantHardLimitReadable = quotaUsage?.hard_limit_readable;
  const tenantWarningLevel = quotaUsage?.tenant_warning_level;

  const columns: ColumnsType<KnowledgeBase> = [
    {
      title: t("common.name"),
      dataIndex: "name",
      key: "name",
      width: 150,
      render: (text: string) => (
        <Tooltip title={text}>
          <div className="font-medium truncate max-w-[140px]">{text}</div>
        </Tooltip>
      ),
    },
    {
      title: t("tenantResources.knowledgeBase.sources"),
      dataIndex: "knowledge_sources",
      key: "knowledge_sources",
      width: 80,
      render: (source: string) => (
        <Tag color="default">{source || t("common.unknown")}</Tag>
      ),
    },
    {
      title: t("tenantResources.knowledgeBase.permission"),
      dataIndex: "ingroup_permission",
      key: "ingroup_permission",
      width: 100,
      render: (permission: string) => {
        const color =
          permission === "EDIT"
            ? "geekblue"
            : permission === "PRIVATE"
              ? "magenta"
              : permission === "READ_ONLY"
                ? "cyan"
                : "default";
        return (
          <Tag color={color}>
            {t(
              `tenantResources.knowledgeBase.permission.${permission || "DEFAULT"}`
            )}
          </Tag>
        );
      },
    },
    {
      title: t("tenantResources.knowledgeBase.documents"),
      dataIndex: "documentCount",
      key: "documentCount",
      width: 60,
      render: (count: number) => count || 0,
    },
    {
      title: t("tenantResources.knowledgeBase.chunks"),
      dataIndex: "chunkCount",
      key: "chunkCount",
      width: 60,
      render: (count: number) => count || 0,
    },
    {
      title: t("tenantResources.knowledgeBase.storeSize"),
      key: "store_size",
      width: 140,
      render: (_: any, record: KnowledgeBase) => {
        const displaySize = record.store_size || "0 B";

        // Non-admin (SU or other roles): plain text only, no per-KB quota controls
        if (!isAdmin) {
          return <span style={{ color: "#666" }}>{displaySize}</span>;
        }

        const indexName = record.index_name || record.id;
        const quotaData = indexName ? quotaMap.get(indexName) : undefined;

        // Inline editing mode
        if (editingQuotaKb === indexName) {
          return (
            <Space direction="vertical" size={2} style={{ width: "100%" }}>
              <Space size={4}>
                <InputNumber
                  value={editingQuotaValue}
                  onChange={(v) => setEditingQuotaValue(v)}
                  addonAfter={editingQuotaUnit}
                  placeholder={t("quota.unlimited", "Unlimited")}
                  style={{ width: 110 }}
                  size="small"
                  autoFocus
                  onPressEnter={() => saveQuotaEdit(indexName)}
                  min={0}
                  precision={0}
                />
                <Segmented
                  size="small"
                  options={["GB", "MB"]}
                  value={editingQuotaUnit}
                  onChange={(val) => setEditingQuotaUnit(val as "GB" | "MB")}
                />
              </Space>
              <Space size={4}>
                <Button
                  size="small"
                  type="primary"
                  loading={savingQuota}
                  onClick={() => saveQuotaEdit(indexName)}
                >
                  ✓
                </Button>
                <Button size="small" onClick={cancelQuotaEdit}>
                  ✗
                </Button>
              </Space>
            </Space>
          );
        }

        // No soft quota: plain text display with inline edit capability
        if (!quotaData || !quotaData.soft_quota_bytes) {
          return (
            <div
              style={{ cursor: "pointer", minWidth: 100 }}
              onClick={() =>
                startEditQuota(indexName, quotaData?.soft_quota_bytes ?? null)
              }
            >
              <span style={{ color: "#666" }}>{displaySize}</span>
              <div style={{ fontSize: 10, color: "#999" }}>
                {t("quota.unlimited", "No limit")}
              </div>
            </div>
          );
        }

        const usagePct = quotaData.usage_pct ?? 0;
        const color = getProgressColor(quotaData.kb_warning_level);
        const softQuotaBytes: number = quotaData.soft_quota_bytes;
        const softQuotaReadable: string =
          softQuotaBytes >= GB
            ? `${(softQuotaBytes / GB).toFixed(0)} GB`
            : softQuotaBytes >= MB
              ? `${(softQuotaBytes / MB).toFixed(0)} MB`
              : `${softQuotaBytes} B`;

        return (
          <div
            style={{ minWidth: 130, cursor: "pointer" }}
            onClick={() =>
              startEditQuota(indexName, quotaData.soft_quota_bytes)
            }
          >
            <Progress
              percent={Math.min(usagePct, 100)}
              size="small"
              strokeColor={color}
              format={() => ""}
              style={{ marginBottom: 2 }}
            />
            <div style={{ fontSize: 12, color: "#666", lineHeight: "14px" }}>
              {displaySize} / {softQuotaReadable}
            </div>
          </div>
        );
      },
    },
    {
      title: t("tenantResources.knowledgeBase.processSource"),
      dataIndex: "process_source",
      key: "process_source",
      width: 80,
      render: (source: string) => (
        <Tag color="default">{source || t("common.unknown")}</Tag>
      ),
    },
    {
      title: t("tenantResources.knowledgeBase.groupNames"),
      dataIndex: "group_ids",
      key: "group_names",
      width: 200,
      render: (groupIds: number[]) => {
        const names = getGroupNames(groupIds);
        return (
          <div className="flex flex-wrap gap-1">
            {names.length > 0 ? (
              names.map((name, index) => (
                <Tag key={index} color="blue" variant="outlined">
                  {name}
                </Tag>
              ))
            ) : (
              <span className="text-gray-400">
                {t("tenantResources.knowledgeBase.noGroups")}
              </span>
            )}
          </div>
        );
      },
    },
    {
      title: t("common.updated"),
      dataIndex: "updatedAt",
      key: "updatedAt",
      width: 120,
      render: (date: string) => formatDateTime(date),
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 140,
      fixed: "right",
      render: (_, record: KnowledgeBase) => {
        if (isExternalSource(record)) {
          return (
            <span className="text-gray-400 text-sm">
              {t("tenantResources.knowledgeBase.externalSourceDisabled")}
            </span>
          );
        }
        return (
          <div className="flex items-center space-x-2">
            <Tooltip title={t("common.edit")}>
              <Button
                type="text"
                icon={<Edit className="h-4 w-4" />}
                onClick={() => openEdit(record)}
                size="small"
              />
            </Tooltip>
            <Tooltip title={t("tenantResources.knowledgeBase.viewSummary")}>
              <Button
                type="text"
                icon={<BookOpen className="h-4 w-4" />}
                onClick={() => openEditSummary(record)}
                size="small"
              />
            </Tooltip>
            <Popconfirm
              title={t("knowledgeBase.modal.deleteConfirm.title")}
              description={t("common.cannotBeUndone")}
              onConfirm={() => handleDelete(record.id)}
              okText={t("common.confirm")}
              cancelText={t("common.cancel")}
            >
              <Tooltip title={t("common.delete")}>
                <Button
                  type="text"
                  danger
                  icon={<Trash2 className="h-4 w-4" />}
                  size="small"
                />
              </Tooltip>
            </Popconfirm>
          </div>
        );
      },
    },
  ];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header: Quota Management button + Inline overview bar (SU + ADMIN) */}
      {canManageQuota && (
        <div className="flex items-center justify-between mb-2 px-1">
          {tenantUsagePct != null && tenantTotalReadable ? (
            <div
              className="flex items-center gap-2 cursor-pointer flex-1 mr-4"
              onClick={() => setQuotaModalVisible(true)}
            >
              <span className="text-sm text-gray-600">
                {t("quota.tenantUsage", "Tenant Usage")}:
              </span>
              <Progress
                percent={Math.min(tenantUsagePct, 100)}
                size="small"
                strokeColor={getProgressColor(quotaUsage?.tenant_warning_level)}
                format={() => ""}
                style={{ flex: 1, maxWidth: 300, marginBottom: 0 }}
              />
              <span className="text-sm text-gray-500 whitespace-nowrap">
                {tenantTotalReadable}
                {tenantHardLimitReadable
                  ? ` / ${tenantHardLimitReadable}`
                  : ""}{" "}
                ({Math.round(tenantUsagePct)}%)
              </span>
            </div>
          ) : (
            <div />
          )}
          <Button
            type="primary"
            icon={<SettingOutlined className="h-4 w-4" />}
            onClick={() => setQuotaModalVisible(true)}
          >
            {userRole === "SU"
              ? t("quota.allocateStorage", "Allocate Storage")
              : t("quota.quotaManagement", "Quota Management")}
          </Button>
        </div>
      )}

      <Table
        columns={columns}
        dataSource={knowledgeBases}
        loading={isLoading}
        rowKey="id"
        pagination={{ pageSize: 10 }}
        className="flex-1 [&_.ant-table]:h-full"
        scroll={{ y: "calc(100vh - 560px)" }}
      />

      {/* Edit Knowledge Base Modal */}
      <KnowledgeBaseEditModal
        open={modalVisible}
        knowledgeBase={editingKnowledge}
        tenantId={tenantId}
        onCancel={() => setModalVisible(false)}
        onSuccess={() => handleRefetch()}
      />

      {/* Quota modal: SU gets simple tenant allocation; ADMIN gets full quota management */}
      {userRole === "SU" && (
        <SuQuotaModal
          open={quotaModalVisible}
          tenantId={tenantId}
          onCancel={() => setQuotaModalVisible(false)}
          onSuccess={() => {
            setQuotaModalVisible(false);
            fetchQuotaUsage();
          }}
          onUsageChange={handleQuotaUsageChange}
        />
      )}
      {userRole === "ADMIN" && (
        <QuotaSettingsModal
          open={quotaModalVisible}
          tenantId={tenantId}
          onCancel={() => setQuotaModalVisible(false)}
          onSuccess={() => {
            setQuotaModalVisible(false);
            fetchQuotaUsage();
          }}
          onUsageChange={handleQuotaUsageChange}
        />
      )}

      <Modal
        title={t("tenantResources.knowledgeBase.viewSummary")}
        open={summaryModalVisible}
        onCancel={() => setSummaryModalVisible(false)}
        footer={[
          <Button
            key="confirm"
            type="primary"
            onClick={() => setSummaryModalVisible(false)}
          >
            {t("common.confirm")}
          </Button>,
        ]}
        width={600}
        confirmLoading={summaryLoading}
      >
        {summaryLoading ? (
          <div className="text-gray-400">{t("common.loading")}</div>
        ) : summaryContent ? (
          <MarkdownRenderer content={summaryContent} />
        ) : (
          <div className="text-gray-400 italic">
            {t("tenantResources.knowledgeBase.noSummary")}
          </div>
        )}
      </Modal>
    </div>
  );
}
