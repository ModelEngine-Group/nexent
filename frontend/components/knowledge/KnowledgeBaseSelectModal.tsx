"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  Modal,
  Table,
  Button,
  Space,
  Tag,
  Empty,
  Spin,
  Typography,
  Input,
} from "antd";
import { Search, Database, FileText, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import log from "@/lib/logger";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { DifyDatasetInfo, DifyDatasetsResponse } from "@/types/knowledgeBase";

const { Text } = Typography;

// Props interface for the KnowledgeBaseSelectModal component
export interface KnowledgeBaseSelectModalProps {
  visible: boolean;
  onClose: () => void;
  onSelect: (dataset: DifyDatasetInfo) => void;
  difyApiBase: string;
  apiKey: string;
  title?: string;
  placeholder?: string;
  currentDatasetId?: string; // Deprecated: use currentDatasetIds instead
  currentDatasetIds?: string[]; // New prop for multiple selection
}

// Loading state type
interface LoadingState {
  loading: boolean;
  message: string;
}

/**
 * KnowledgeBaseSelectModal - A reusable modal component for selecting Dify knowledge bases
 *
 * Features:
 * - Fetches and displays Dify datasets from the configured API
 * - Supports pagination for large datasets
 * - Search/filter functionality
 * - Displays dataset information (name, document count, etc.)
 * - Allows single selection of knowledge base
 */
export function KnowledgeBaseSelectModal({
  visible,
  onClose,
  onSelect,
  difyApiBase,
  apiKey,
  title,
  placeholder,
  currentDatasetId,
  currentDatasetIds,
}: KnowledgeBaseSelectModalProps) {
  const { t } = useTranslation("common");

  const [datasets, setDatasets] = useState<DifyDatasetInfo[]>([]);
  const [loading, setLoading] = useState<LoadingState>({ loading: true, message: "" });
  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 10,
    total: 0,
    hasMore: false,
  });
  const [searchText, setSearchText] = useState("");

  // Default title if not provided
  const modalTitle = title || t("knowledgeBase.selectModal.title") || "Select Knowledge Base";
  const searchPlaceholder = placeholder || t("knowledgeBase.selectModal.searchPlaceholder") || "Search knowledge bases...";

  // Fetch datasets from Dify API
  const fetchDatasets = useCallback(
    async (page: number = 1, pageSize: number = 10) => {
      if (!difyApiBase || !apiKey) {
        log.warn("Dify API configuration is missing");
        setLoading({ loading: false, message: "" });
        return;
      }

      setLoading({ loading: true, message: t("knowledgeBase.selectModal.loading") || "Loading knowledge bases..." });

      try {
        const response: DifyDatasetsResponse = await knowledgeBaseService.fetchDifyDatasets(
          difyApiBase,
          apiKey,
          page,
          pageSize
        );

        setDatasets(response.indices_info || []);
        setPagination({
          current: page,
          pageSize,
          total: response.pagination.total || 0,
          hasMore: response.pagination.has_more || false,
        });
      } catch (error) {
        log.error("Failed to fetch Dify datasets:", error);
        // Show error state but don't throw
      } finally {
        setLoading({ loading: false, message: "" });
      }
    },
    [difyApiBase, apiKey, t]
  );

  // Fetch datasets when modal becomes visible
  useEffect(() => {
    if (visible && difyApiBase && apiKey) {
      fetchDatasets(1, pagination.pageSize);
    }
  }, [visible, difyApiBase, apiKey, fetchDatasets, pagination.pageSize]);

  // Handle table pagination change
  const handleTableChange = (newPagination: any) => {
    fetchDatasets(newPagination.current, newPagination.pageSize);
  };

  // Handle search
  const handleSearch = (value: string) => {
    setSearchText(value);
  };

  // Filter datasets based on search text
  const filteredDatasets = datasets.filter((dataset) => {
    if (!searchText) return true;
    const searchLower = searchText.toLowerCase();
    return (
      dataset.display_name?.toLowerCase().includes(searchLower) ||
      dataset.name?.toLowerCase().includes(searchLower)
    );
  });

  // Handle dataset selection
  const handleSelect = (dataset: DifyDatasetInfo) => {
    onSelect(dataset);
    onClose();
  };

  // Format timestamp to readable date
  const formatDate = (timestamp: number) => {
    if (!timestamp) return "-";
    return new Date(timestamp).toLocaleString();
  };

  // Check if a dataset is currently selected (supports both single and multiple selection)
  const isSelected = (dataset: DifyDatasetInfo) => {
    // Support multiple selection via currentDatasetIds
    if (currentDatasetIds && Array.isArray(currentDatasetIds)) {
      return currentDatasetIds.includes(dataset.name);
    }
    // Fallback to single selection for backward compatibility
    return currentDatasetId === dataset.name;
  };

  // Table columns definition
  const columns = [
    {
      title: t("knowledgeBase.selectModal.columns.name") || "Name",
      dataIndex: "display_name",
      key: "display_name",
      render: (text: string, record: DifyDatasetInfo) => (
        <div className="flex items-center gap-2">
          <Database size={16} className="text-blue-500" />
          <div>
            <div className="font-medium">{text || record.name}</div>
            <Text type="secondary" className="text-xs">
              ID: {record.name}
            </Text>
          </div>
        </div>
      ),
    },
    {
      title: t("knowledgeBase.selectModal.columns.documents") || "Documents",
      dataIndex: ["stats", "base_info", "doc_count"],
      key: "doc_count",
      width: 120,
      render: (count: number) => (
        <Tag color="blue">
          <Space size={4}>
            <FileText size={12} />
            {count || 0}
          </Space>
        </Tag>
      ),
    },
    {
      title: t("knowledgeBase.selectModal.columns.source") || "Source",
      dataIndex: ["stats", "base_info", "process_source"],
      key: "process_source",
      width: 100,
      render: (source: string) => <Tag>{source || "Dify"}</Tag>,
    },
    {
      title: t("knowledgeBase.selectModal.columns.updated") || "Updated",
      dataIndex: ["stats", "base_info", "update_date"],
      key: "update_date",
      width: 180,
      render: (date: number) => (
        <Text type="secondary" className="text-xs">
          {formatDate(date)}
        </Text>
      ),
    },
    {
      title: "",
      key: "action",
      width: 100,
      render: (_: any, record: DifyDatasetInfo) => (
        <Button
          type={isSelected(record) ? "default" : "primary"}
          size="small"
          onClick={() => handleSelect(record)}
        >
          {isSelected(record)
            ? t("knowledgeBase.selectModal.selected")
            : t("knowledgeBase.selectModal.select")}
        </Button>
      ),
    },
  ];

  return (
    <Modal
      title={modalTitle}
      open={visible}
      onCancel={onClose}
      footer={null}
      width={800}
      destroyOnHidden
      centered
    >
      <div className="space-y-4">
        {/* Search and refresh bar */}
        <div className="flex items-center gap-4">
          <Input
            placeholder={searchPlaceholder}
            prefix={<Search size={16} className="text-gray-400" />}
            value={searchText}
            onChange={(e) => handleSearch(e.target.value)}
            allowClear
            className="flex-1"
          />
          <Button
            icon={<RefreshCw size={16} />}
            onClick={() => fetchDatasets(1, pagination.pageSize)}
            loading={loading.loading}
          >
            {t("knowledgeBase.selectModal.refresh") || "Refresh"}
          </Button>
        </div>

        {/* Table or loading/empty state */}
        {loading.loading ? (
          <div className="flex items-center justify-center py-12">
            <Spin size="large" />
            <Text type="secondary" className="ml-4">
              {loading.message}
            </Text>
          </div>
        ) : filteredDatasets.length === 0 ? (
          <Empty
            description={
              searchText
                ? t("knowledgeBase.selectModal.noResults") || "No knowledge bases match your search"
                : t("knowledgeBase.selectModal.noData") || "No knowledge bases available"
            }
          />
        ) : (
          <Table
            columns={columns}
            dataSource={filteredDatasets}
            rowKey={(record) => record.name}
            pagination={{
              current: pagination.current,
              pageSize: pagination.pageSize,
              total: pagination.total,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total) =>
                t("knowledgeBase.selectModal.total") ||
                `Total ${total} items`,
            }}
            onChange={handleTableChange}
            loading={loading.loading}
            size="middle"
            rowClassName={(record) =>
              isSelected(record) ? "bg-blue-50" : ""
            }
          />
        )}
      </div>
    </Modal>
  );
}

export default KnowledgeBaseSelectModal;
