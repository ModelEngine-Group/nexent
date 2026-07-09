"use client";

/**
 * KnowledgeBaseGrid — Phase 3 Component 3
 *
 * A **controlled** grid component that displays a list of knowledge bases as
 * cards. It does NOT manage its own data — the parent provides the KB list
 * and all callbacks. This component is purely presentational.
 *
 * Responsibilities:
 * - Render KB cards in a responsive grid layout
 * - Show a "create new KB" card when showCreateButton is true
 * - Display per-KB metadata: name, description, document/chunk counts,
 *   embedding model, and adapter platform badge
 * - Provide delete confirmation via Popconfirm
 * - Show loading spinner and empty states
 */

import React from "react";
import {
  Button,
  Card,
  Empty,
  Popconfirm,
  Space,
  Spin,
  Tag,
} from "antd";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Descriptor for a single knowledge base entry. */
export interface KnowledgeBaseItem {
  /** Unique knowledge base identifier within an adapter. */
  kb_id: string;
  /** Numeric adapter identifier that owns this KB. */
  adapter_id: number;
  /** Platform name of the adapter (e.g. "local", "dify", "aidp"). */
  adapter_platform: string;
  /** Human-readable KB name. */
  name: string;
  /** Optional description text. */
  description?: string;
  /** Number of documents uploaded to this KB. */
  document_count: number;
  /** Number of chunks produced after splitting. */
  chunk_count: number;
  /** Name of the embedding model used, if any. */
  embedding_model?: string;
}

/** Props for the KnowledgeBaseGrid component. */
export interface KnowledgeBaseGridProps {
  /** Array of KB descriptors to display. */
  kbs: KnowledgeBaseItem[];
  /** Whether data is currently being loaded. */
  loading?: boolean;
  /** Whether to show the "create new KB" card. */
  showCreateButton?: boolean;
  /** Callback when the create card is clicked. */
  onCreateClick?: () => void;
  /** Callback when a KB card is clicked — receives kb_id and adapter_id. */
  onKbClick?: (kbId: string, adapterId: number) => void;
  /** Callback when delete is confirmed — receives kb_id and adapter_id. */
  onKbDelete?: (kbId: string, adapterId: number) => Promise<void>;
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const gridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
  gap: 16,
};

const createCardStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  minHeight: 200,
  cursor: "pointer",
};

const centerStyle: React.CSSProperties = {
  textAlign: "center",
};

const plusIconStyle: React.CSSProperties = {
  fontSize: 48,
  color: "#1890ff",
};

const createTextStyle: React.CSSProperties = {
  marginTop: 16,
  fontSize: 16,
};

const metaStyle: React.CSSProperties = {
  marginTop: 16,
};

const loadingContainerStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "center",
  padding: 40,
};

const emptyStyle: React.CSSProperties = {
  marginTop: 40,
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * KnowledgeBaseGrid renders a responsive grid of KB cards with optional
 * create button, delete confirmation, loading spinner, and empty states.
 */
const KnowledgeBaseGrid: React.FC<KnowledgeBaseGridProps> = ({
  kbs,
  loading = false,
  showCreateButton = false,
  onCreateClick,
  onKbClick,
  onKbDelete,
}) => {
  return (
    <>
      {/* Grid of cards */}
      <div style={gridStyle}>
        {/* Create-new card — only rendered when explicitly requested */}
        {showCreateButton && (
          <Card
            key="create-new"
            hoverable
            onClick={onCreateClick}
            style={createCardStyle}
          >
            <div style={centerStyle}>
              <PlusOutlined style={plusIconStyle} />
              <p style={createTextStyle}>创建新知识库</p>
            </div>
          </Card>
        )}

        {/* One card per knowledge base */}
        {kbs.map((kb) => (
          <Card
            key={`${kb.adapter_id}:${kb.kb_id}`}
            hoverable
            onClick={() => onKbClick?.(kb.kb_id, kb.adapter_id)}
            extra={
              <Popconfirm
                title="确认删除此知识库？"
                description="删除后不可恢复，包含的所有文档也将被删除。"
                onConfirm={(e) => {
                  e?.stopPropagation();
                  onKbDelete?.(kb.kb_id, kb.adapter_id);
                }}
                onCancel={(e) => e?.stopPropagation()}
                okText="删除"
                cancelText="取消"
              >
                <Button
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={(e) => e.stopPropagation()}
                />
              </Popconfirm>
            }
          >
            <Card.Meta
              title={
                <Space>
                  <span>{kb.name}</span>
                  <Tag color={kb.adapter_platform === "local" ? "blue" : "purple"}>
                    {kb.adapter_platform}
                  </Tag>
                </Space>
              }
              description={kb.description || "暂无描述"}
            />
            <div style={metaStyle}>
              <p>文档数：{kb.document_count}</p>
              <p>块数：{kb.chunk_count}</p>
              {kb.embedding_model && <p>Embedding 模型：{kb.embedding_model}</p>}
            </div>
          </Card>
        ))}
      </div>

      {/* Loading indicator */}
      {loading && (
        <div style={loadingContainerStyle}>
          <Spin size="large" />
        </div>
      )}

      {/* Empty state — no create option */}
      {!loading && kbs.length === 0 && !showCreateButton && (
        <Empty description="暂无知识库" style={emptyStyle} />
      )}

      {/* Empty state — create option available */}
      {!loading && kbs.length === 0 && showCreateButton && (
        <Empty description="暂无知识库，点击上方卡片创建" style={emptyStyle} />
      )}
    </>
  );
};

export default KnowledgeBaseGrid;
