"use client";

/**
 * KBDetailDrawer — Phase 3 Component 5
 *
 * A drawer that displays detailed information about a selected knowledge base,
 * including metadata, document management (list / upload / delete / status),
 * and local-adapter-exclusive shortcuts that open existing pages in new tabs.
 *
 * Responsibilities:
 * - Fetch and display KB metadata (id, name, description, counts, model)
 * - List documents with status tags, upload new files, delete with confirmation
 * - Show per-document indexing status in a modal dialog
 * - Render local-platform-exclusive shortcuts (summary / chunks / embedding)
 *   that navigate to existing pages via window.open(..., '_blank')
 */

import React, { useRef, useState } from "react";
import {
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Modal,
  Popconfirm,
  Space,
  Spin,
  Table,
  Tag,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { UploadOutlined } from "@ant-design/icons";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import unifiedKbManager from "@/services/unifiedKnowledgeBaseService";
import type { DocSummary } from "@/types/unifiedKnowledgeBase";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Props for the KBDetailDrawer component. */
export interface KBDetailDrawerProps {
  /** Whether the drawer is visible. */
  visible: boolean;
  /** ID of the selected knowledge base (null when nothing is selected). */
  kbId: string | null;
  /** Numeric adapter ID that owns the KB. */
  adapterId: number | null;
  /** Platform of the adapter (e.g. "local", "dify"). Caller supplies from context. */
  adapterPlatform: string | null;
  /** Called after document upload / delete so the parent can refresh its data. */
  onUpdated: () => void;
  /** Called when the drawer is closed. */
  onClosed: () => void;
  /** Optional error callback — receives the error and a context string. */
  onError?: (err: Error, context: string) => void;
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const loadingContainerStyle: React.CSSProperties = {
  textAlign: "center",
  padding: 40,
};

const full_width_space: React.CSSProperties = {
  width: "100%",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format a byte count into a human-readable string (B / KB / MB / GB). */
const formatBytes = (bytes: number): string => {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
};

/** Render a document status string as a coloured Antd Tag. */
const renderDocStatus = (status: string): React.ReactNode => {
  const statusMap: Record<string, { color: string; text: string }> = {
    indexing: { color: "blue", text: "索引中" },
    completed: { color: "green", text: "已完成" },
    failed: { color: "red", text: "失败" },
  };
  const config = statusMap[status] ?? { color: "default", text: status };
  return <Tag color={config.color}>{config.text}</Tag>;
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * KBDetailDrawer shows KB metadata, manages documents (list / upload / delete),
 * and exposes local-adapter-exclusive shortcuts in new browser tabs.
 */
const KBDetailDrawer: React.FC<KBDetailDrawerProps> = ({
  visible,
  kbId,
  adapterId,
  adapterPlatform,
  onUpdated,
  onClosed,
  onError,
}) => {
  const queryClient = useQueryClient();

  // -- local state -----------------------------------------------------------
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [docStatusId, setDocStatusId] = useState<string | null>(null);
  const [docStatusModalVisible, setDocStatusModalVisible] = useState(false);

  // -- queries ---------------------------------------------------------------

  /** Fetch the selected KB's metadata directly via getKb (single-record lookup). */
  const kbQuery = useQuery({
    queryKey: ["unified-kb", "selected-kb", kbId, adapterId],
    queryFn: () =>
      unifiedKbManager.getKb(adapterId!, kbId!, adapterPlatform ?? "unknown"),
    enabled: visible && kbId !== null && adapterId !== null && adapterPlatform !== null,
  });

  /** Fetch the document list for the selected KB. */
  const docsQuery = useQuery({
    queryKey: ["unified-kb", "docs-in-kb", kbId, adapterId],
    queryFn: () =>
      unifiedKbManager.listDocuments(adapterId!, kbId!, { pageSize: 50 }),
    enabled: visible && kbId !== null && adapterId !== null,
  });

  /** Fetch per-document indexing status (triggered on demand). */
  const docStatusQuery = useQuery({
    queryKey: ["unified-kb", "doc-status", docStatusId],
    queryFn: () =>
      unifiedKbManager.getDocumentStatus(adapterId!, kbId!, docStatusId!),
    enabled: docStatusId !== null,
  });

  // -- document table columns ------------------------------------------------

  const docColumns: ColumnsType<DocSummary> = [
    { title: "名称", dataIndex: "name" },
    {
      title: "大小",
      dataIndex: "size",
      render: (size: number) => formatBytes(size),
    },
    {
      title: "状态",
      dataIndex: "status",
      render: (status: string) => renderDocStatus(status),
    },
    {
      title: "操作",
      width: 150,
      render: (_: unknown, doc: DocSummary) => (
        <Space>
          <Button size="small" onClick={() => handleDocStatusClick(doc)}>
            状态
          </Button>
          <Popconfirm
            title="确认删除此文档？"
            onConfirm={() => handleDocDelete(doc.document_id)}
          >
            <Button size="small" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // -- handlers --------------------------------------------------------------

  /** Open the hidden file input to trigger the native file picker. */
  const handleUploadClick = (): void => {
    fileInputRef.current?.click();
  };

  /** Upload selected files and refresh queries on success. */
  const handleFileSelect = async (
    e: React.ChangeEvent<HTMLInputElement>,
  ): Promise<void> => {
    const files = Array.from(e.target.files ?? []);
    if (files.length === 0) return;

    setUploading(true);
    try {
      await unifiedKbManager.uploadDocuments(adapterId!, kbId!, files, {
        chunking_strategy: "basic",
      });
      message.success(`${files.length} 个文件上传成功`);
      onUpdated();
      queryClient.invalidateQueries({
        queryKey: ["unified-kb", "docs-in-kb", kbId],
      });
    } catch (err) {
      onError?.(err as Error, "文件上传失败");
      message.error("文件上传失败，请重试");
    } finally {
      setUploading(false);
      // Clear input value so the same file can be re-selected later.
      e.target.value = "";
    }
  };

  /** Delete a document and refresh queries on success. */
  const handleDocDelete = async (docId: string): Promise<void> => {
    try {
      await unifiedKbManager.deleteDocument(adapterId!, kbId!, docId);
      message.success("文档删除成功");
      onUpdated();
      queryClient.invalidateQueries({
        queryKey: ["unified-kb", "docs-in-kb", kbId],
      });
    } catch (err) {
      onError?.(err as Error, "文档删除失败");
      message.error("删除失败，请重试");
    }
  };

  /** Open the document-status modal for a specific document. */
  const handleDocStatusClick = (doc: DocSummary): void => {
    setDocStatusId(doc.document_id);
    setDocStatusModalVisible(true);
  };

  /** Reset local state and notify parent that the drawer is closing. */
  const handleClose = (): void => {
    setDocStatusId(null);
    setDocStatusModalVisible(false);
    onClosed();
  };

  // -- render ----------------------------------------------------------------

  return (
    <>
      <Drawer
        title={kbQuery.data?.name ?? "知识库详情"}
        open={visible}
        onClose={handleClose}
        width={640}
      >
        {/* Loading state */}
        {kbQuery.isLoading && (
          <div style={loadingContainerStyle}>
            <Spin size="large" />
          </div>
        )}

        {/* Main content — only rendered once KB data is available */}
        {kbQuery.data && (
          <Space direction="vertical" style={full_width_space} size="large">
            {/* Section 1 — basic metadata */}
            <Card title="基本信息">
              <Descriptions bordered column={1}>
                <Descriptions.Item label="ID">
                  {kbQuery.data.id}
                </Descriptions.Item>
                <Descriptions.Item label="名称">
                  {kbQuery.data.name}
                </Descriptions.Item>
                <Descriptions.Item label="描述">
                  {kbQuery.data.description || "暂无描述"}
                </Descriptions.Item>
                <Descriptions.Item label="文档数">
                  {kbQuery.data.document_count}
                </Descriptions.Item>
                <Descriptions.Item label="块数">
                  {kbQuery.data.chunk_count}
                </Descriptions.Item>
                {kbQuery.data.embedding_model && (
                  <Descriptions.Item label="Embedding 模型">
                    {kbQuery.data.embedding_model}
                  </Descriptions.Item>
                )}
              </Descriptions>
            </Card>

            {/* Section 2 — document management */}
            <Card
              title="文档管理"
              extra={
                <Button
                  type="primary"
                  icon={<UploadOutlined />}
                  onClick={handleUploadClick}
                  loading={uploading}
                >
                  上传
                </Button>
              }
            >
              <input
                ref={fileInputRef}
                type="file"
                multiple
                style={{ display: "none" }}
                onChange={handleFileSelect}
              />
              <Table<DocSummary>
                dataSource={docsQuery.data?.docs ?? []}
                loading={docsQuery.isLoading}
                rowKey="document_id"
                size="small"
                pagination={false}
                columns={docColumns}
              />
              {docsQuery.data && docsQuery.data.docs.length === 0 && (
                <Empty description="暂无文档" />
              )}
            </Card>

            {/* Section 3 — local-adapter-exclusive shortcuts */}
            {kbQuery.data.adapter_platform === "local" && (
              <Card title="本地专属功能">
                <Space direction="vertical">
                  <Button
                    onClick={() =>
                      window.open(
                        `/knowledges/${kbQuery.data!.id}/summary`,
                        "_blank",
                      )
                    }
                  >
                    查看/编辑摘要
                  </Button>
                  <Button
                    onClick={() =>
                      window.open(
                        `/knowledges/${kbQuery.data!.id}/chunks`,
                        "_blank",
                      )
                    }
                  >
                    查看 Chunk
                  </Button>
                  <Button
                    onClick={() =>
                      window.open(
                        `/knowledges/${kbQuery.data!.id}/embedding`,
                        "_blank",
                      )
                    }
                  >
                    配置 Embedding 模型
                  </Button>
                </Space>
              </Card>
            )}
          </Space>
        )}
      </Drawer>

      {/* Document status modal */}
      <Modal
        title={`文档 ${docsQuery.data?.docs.find((d) => d.document_id === docStatusId)?.name ?? ""} 状态`}
        open={docStatusModalVisible}
        onCancel={() => {
          setDocStatusModalVisible(false);
          setDocStatusId(null);
        }}
        footer={null}
      >
        {docStatusQuery.isLoading && <Spin />}
        {docStatusQuery.data && (
          <Descriptions bordered column={1}>
            <Descriptions.Item label="状态">
              {renderDocStatus(docStatusQuery.data.status)}
            </Descriptions.Item>
            <Descriptions.Item label="进度">
              {docStatusQuery.data.progress_pct ?? 0}%
            </Descriptions.Item>
            <Descriptions.Item label="块数">
              {docStatusQuery.data.chunk_count ?? 0}
            </Descriptions.Item>
            {docStatusQuery.data.total_chunks && (
              <Descriptions.Item label="总块数">
                {docStatusQuery.data.total_chunks}
              </Descriptions.Item>
            )}
            {docStatusQuery.data.error_message && (
              <Descriptions.Item label="错误信息">
                <span style={{ color: "red" }}>
                  {docStatusQuery.data.error_message}
                </span>
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
      </Modal>
    </>
  );
};

export default KBDetailDrawer;
