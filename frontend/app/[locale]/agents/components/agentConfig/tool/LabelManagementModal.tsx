"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Table, Select, App } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useQueryClient } from "@tanstack/react-query";
import { API_ENDPOINTS } from "@/services/api";
import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";

interface LabelManagementModalProps {
  open: boolean;
  onClose: () => void;
  availableTools: any[];
}

interface ToolRow {
  id: string;
  name: string;
  source: string;
  labels: string[];
  updatedBy: string;
}

export default function LabelManagementModal({
  open,
  onClose,
  availableTools,
}: LabelManagementModalProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [dataSource, setDataSource] = useState<ToolRow[]>([]);
  const builtRef = useRef(false);

  // Collect all unique labels from dataSource for Select suggestions
  const allExistingLabels = useMemo(() => {
    const labelSet = new Set<string>();
    dataSource.forEach((row) => row.labels.forEach((l: string) => labelSet.add(l)));
    return Array.from(labelSet).sort((a, b) => a.localeCompare(b));
  }, [dataSource]);

  // Build dataSource once per open cycle. Using builtRef lets us
  // handle the case where availableTools arrives after the modal is already open.
  useEffect(() => {
    if (open) {
      if (!builtRef.current && availableTools.length > 0) {
        const rows: ToolRow[] = availableTools.map((tool: any) => ({
          id: tool.id,
          name: tool.name,
          source: tool.source || "",
          labels: Array.isArray(tool.labels) ? [...tool.labels] : [],
          updatedBy: tool.updated_by || "",
        }));
        setDataSource(rows);
        builtRef.current = true;
      }
    } else {
      setDataSource([]);
      builtRef.current = false;
    }
  }, [open, availableTools]);

  const handleLabelsChange = useCallback(
    async (toolId: string, newLabels: string[]) => {
      // Optimistically update local state
      setDataSource((prev) =>
        prev.map((row) =>
          row.id === toolId ? { ...row, labels: newLabels } : row
        )
      );

      // Persist to backend, then synchronously update cache so parent sees fresh data
      try {
        await fetch(API_ENDPOINTS.tool.labels, {
          method: "PUT",
          headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
          body: JSON.stringify({ tool_id: parseInt(toolId), labels: newLabels }),
        });
        // Synchronous cache update — no timing gaps, no refetch race
        queryClient.setQueryData(["tools"], (old: any[]) => {
          if (!old) return old;
          return old.map((tool: any) =>
            tool.id === toolId ? { ...tool, labels: newLabels } : tool
          );
        });
      } catch (err) {
        log.warn("Failed to update tool labels:", err);
        message.error(t("toolConfig.message.labelsSaveFailed"));
      }
    },
    [message, t, queryClient]
  );

  const columns: ColumnsType<ToolRow> = [
    {
      title: t("toolConfig.column.toolName"),
      dataIndex: "name",
      key: "name",
      width: 200,
    },
    {
      title: t("toolConfig.column.source"),
      dataIndex: "source",
      key: "source",
      width: 100,
    },
    {
      title: t("toolConfig.column.updatedBy"),
      dataIndex: "updatedBy",
      key: "updatedBy",
      width: 140,
      render: (val: string) => (
        <span className="text-xs text-gray-400">{val || "—"}</span>
      ),
    },
    {
      title: t("toolConfig.column.labels"),
      dataIndex: "labels",
      key: "labels",
      render: (labels: string[], record: ToolRow) => (
        <Select
          mode="tags"
          value={labels}
          onChange={(val: string[]) => handleLabelsChange(record.id, val)}
          placeholder={t("toolConfig.labelPlaceholder")}
          style={{ width: "100%", minWidth: 250 }}
          tokenSeparators={[","]}
          options={allExistingLabels.map((l) => ({ label: l, value: l }))}
        />
      ),
    },
  ];

  return (
    <Modal
      title={t("toolConfig.title.manageLabels")}
      open={open}
      onCancel={onClose}
      mask={{ closable: true }}
      footer={null}
      width={1100}
      zIndex={1100}
    >
      <Table
        dataSource={dataSource}
        columns={columns}
        rowKey="id"
        size="small"
        pagination={{ pageSize: 25, size: "small" }}
        scroll={{ y: 600 }}
      />
    </Modal>
  );
}
