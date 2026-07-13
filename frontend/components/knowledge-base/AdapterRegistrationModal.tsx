"use client";

/**
 * AdapterRegistrationModal — Adapter Management UI.
 *
 * Two sections:
 *   1. **Registered adapters** — lists all adapters (including disabled ones)
 *      with health status, capability tags, and actions (health check,
 *      enable/disable, delete). The `local` adapter cannot be deleted.
 *   2. **Available platforms** — placeholder cards for platforms whose adapter
 *      classes have not yet been implemented. Filtered so any platform that
 *      already has a registered adapter is removed from this list.
 *
 * Fires `onRegistered` after any successful mutation (enable/disable/delete)
 * so the parent can refresh its adapter list query.
 */

import React, { useMemo } from "react";
import {
  Badge,
  Button,
  Divider,
  List,
  message,
  Modal,
  Popconfirm,
  Space,
  Spin,
  Switch,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import {
  CheckCircleOutlined,
  DatabaseOutlined,
  ExclamationCircleOutlined,
  ReloadOutlined,
} from "@ant-design/icons";

import unifiedKbManager from "@/services/unifiedKnowledgeBaseService";
import type { AdapterInfo } from "@/types/unifiedKnowledgeBase";
import type { UnifiedAdapterCapabilities } from "@/types/unifiedKB";

const { Text } = Typography;

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface AdapterRegistrationModalProps {
  visible: boolean;
  onCancel: () => void;
  /** Called after any successful adapter mutation so the parent can refresh. */
  onRegistered?: () => void;
}

// ---------------------------------------------------------------------------
// Placeholder data for not-yet-implemented platforms
// ---------------------------------------------------------------------------

interface PlaceholderAdapter {
  platform: string;
  name: string;
  description: string;
  icon: string;
  docUrl: string;
}

const PLACEHOLDER_ADAPTERS: PlaceholderAdapter[] = [
  {
    platform: "dify",
    name: "Dify 知识库",
    description: "接入 Dify 平台的 datasets，实现跨平台知识检索",
    icon: "🌐",
    docUrl: "https://docs.dify.ai/guides/knowledge-base",
  },
  {
    platform: "aidp",
    name: "AIDP 知识库",
    description: "接入 AIDP 平台的企业知识管理功能",
    icon: "🤖",
    docUrl: "#",
  },
  {
    platform: "datamate",
    name: "DataMate 知识库",
    description: "接入 DataMate 数据管理平台的文档库",
    icon: "💾",
    docUrl: "#",
  },
  {
    platform: "haotian",
    name: "Haotian 知识库",
    description: "接入 Haotian 平台的 knowledge sets",
    icon: "📚",
    docUrl: "#",
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const QUERY_KEY = ["unified-kb"] as const;

/** Render a colour-coded health badge for an adapter. */
function renderHealthBadge(adapter: AdapterInfo): React.ReactNode {
  const status = adapter.health_status;
  if (status === "healthy" || status === "ok") {
    return (
      <Tooltip title="健康检查通过">
        <Badge status="success" text="健康" />
      </Tooltip>
    );
  }
  if (status === "error" || status === "unhealthy") {
    return (
      <Tooltip title="健康检查失败">
        <Badge status="error" text="异常" />
      </Tooltip>
    );
  }
  return (
    <Tooltip title="尚未执行健康检查">
      <Badge status="warning" text="未检查" />
    </Tooltip>
  );
}

/** Compact summary: how many capabilities does the adapter claim? */
function capabilitiesSummary(cap?: UnifiedAdapterCapabilities): string {
  if (!cap) return "尚无能力声明";
  const parts: string[] = [];
  if (cap.create_knowledge_base) parts.push("创建KB");
  if (cap.delete_knowledge_base) parts.push("删除KB");
  if (cap.upload_document) parts.push("上传文档");
  if (cap.search_modes.length > 0) parts.push(`${cap.search_modes.length}种检索`);
  if (cap.supports_rerank) parts.push("重排序");
  return parts.length > 0 ? parts.join(" · ") : "基础能力";
}

/** Platform icon — local gets DatabaseOutlined, others get default. */
function platformIcon(platform: string): React.ReactNode {
  return platform === "local" ? (
    <DatabaseOutlined style={{ fontSize: 20, color: "#1890ff" }} />
  ) : (
    <span style={{ fontSize: 20 }}>🔗</span>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const AdapterRegistrationModal: React.FC<AdapterRegistrationModalProps> = ({
  visible,
  onCancel,
  onRegistered,
}) => {
  const queryClient = useQueryClient();

  // -- Data fetching ----------------------------------------------------------

  const { data: adapters, isLoading } = useQuery({
    queryKey: [...QUERY_KEY, "adapter-mgmt"],
    queryFn: () => unifiedKbManager.listAllAdaptersForManagement(),
    enabled: visible,
    refetchOnMount: true,
  });

  // -- Mutations --------------------------------------------------------------

  const healthCheckMut = useMutation({
    mutationFn: (id: number) => unifiedKbManager.checkAdapterHealth(id),
    onSuccess: (_, id) => {
      message.success("健康检查完成");
      // Refresh capabilities so the capability summary stays fresh.
      unifiedKbManager.getAdapterCapabilities(id).catch(() => undefined);
      // Only invalidate internal query state — do NOT close the modal or
      // call onRegistered (the parent KB list refreshes on modal close only).
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: (err: Error) => message.error(`健康检查失败: ${err.message}`),
  });

  const toggleEnabledMut = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      unifiedKbManager.updateAdapter(id, { enabled }),
    onSuccess: (_, vars) => {
      message.success(vars.enabled ? "已启用" : "已禁用");
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      // Do NOT call onRegistered — only invalidate in place.
    },
    onError: (err: Error) => message.error(`操作失败: ${err.message}`),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => unifiedKbManager.deleteAdapter(id),
    onSuccess: () => {
      message.success("适配器已删除");
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
      onRegistered?.();
    },
    onError: (err: Error) => message.error(`删除失败: ${err.message}`),
  });

  // -- Derived ---------------------------------------------------------------

  /** Placeholder platforms that don't yet have a registered adapter. */
  const availablePlaceholders = useMemo(() => {
    const registeredPlatforms = new Set<string>(
      (adapters ?? []).map((a) => a.platform),
    );
    return PLACEHOLDER_ADAPTERS.filter(
      (p) => !registeredPlatforms.has(p.platform),
    );
  }, [adapters]);

  // -- Render ----------------------------------------------------------------

  return (
    <Modal
      open={visible}
      title="适配器管理"
      onCancel={onCancel}
      width={720}
      footer={null}
      destroyOnClose
    >
      {/* ─── Section 1: Registered adapters ─────────────────────────────── */}
      <Text strong style={{ display: "block", marginBottom: 12 }}>
        已注册适配器
      </Text>

      <Spin spinning={isLoading}>
        <List<AdapterInfo>
          dataSource={adapters ?? []}
          locale={{ emptyText: "暂无已注册适配器" }}
          renderItem={(adapter) => {
            const isLocal = adapter.platform === "local";
            return (
              <List.Item
                actions={[
                  <Button
                    key="health"
                    size="small"
                    icon={<ReloadOutlined />}
                    loading={healthCheckMut.isPending && healthCheckMut.variables === adapter.adapter_id}
                    onClick={() => healthCheckMut.mutate(adapter.adapter_id)}
                  >
                    检查
                  </Button>,
                  <Tooltip
                    key="toggle"
                    title={adapter.enabled ? "禁用适配器" : "启用适配器"}
                  >
                    <Switch
                      size="small"
                      checked={adapter.enabled}
                      loading={
                        toggleEnabledMut.isPending &&
                        toggleEnabledMut.variables?.id === adapter.adapter_id
                      }
                      onChange={(checked) =>
                        toggleEnabledMut.mutate({
                          id: adapter.adapter_id,
                          enabled: checked,
                        })
                      }
                    />
                  </Tooltip>,
                  ...(isLocal
                    ? []
                    : [
                        <Popconfirm
                          key="delete"
                          title="确认删除此适配器？删除后无法恢复。"
                          okText="删除"
                          cancelText="取消"
                          onConfirm={() => deleteMut.mutate(adapter.adapter_id)}
                          icon={<ExclamationCircleOutlined style={{ color: "#ff4d4f" }} />}
                        >
                          <Button size="small" danger>
                            删除
                          </Button>
                        </Popconfirm>,
                      ]),
                ]}
              >
                <List.Item.Meta
                  avatar={platformIcon(adapter.platform)}
                  title={
                    <Space>
                      <span>{adapter.name}</span>
                      <Tag color={isLocal ? "blue" : "purple"}>
                        {adapter.platform}
                      </Tag>
                      {renderHealthBadge(adapter)}
                      {!adapter.enabled && <Tag color="default">已禁用</Tag>}
                    </Space>
                  }
                  description={capabilitiesSummary(adapter.capabilities)}
                />
              </List.Item>
            );
          }}
        />
      </Spin>

      {/* ─── Section 2: Available platforms ────────────────────────────── */}
      {availablePlaceholders.length > 0 && (
        <>
          <Divider />
          <Text strong style={{ display: "block", marginBottom: 12 }}>
            可用平台（尚未注册）
          </Text>
          <List<PlaceholderAdapter>
            dataSource={availablePlaceholders}
            renderItem={(adapter) => (
              <List.Item
                actions={[
                  <Button key="action" disabled size="small">
                    即将推出
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  avatar={<span style={{ fontSize: 24 }}>{adapter.icon}</span>}
                  title={
                    <Space>
                      <Tag color="orange">Coming soon</Tag>
                      {adapter.name}
                    </Space>
                  }
                  description={
                    <>
                      <span>{adapter.description}</span>
                      {adapter.docUrl !== "#" && (
                        <>
                          {" · "}
                          <a
                            href={adapter.docUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            查看文档
                          </a>
                        </>
                      )}
                    </>
                  }
                />
              </List.Item>
            )}
          />
        </>
      )}

      {/* ─── Footer note for local adapter ────────────────────────────── */}
      {!isLoading && adapters?.some((a) => a.platform === "local") && (
        <>
          <Divider />
          <Space>
            <CheckCircleOutlined style={{ color: "#52c41a" }} />
            <Text type="secondary">
              本地知识库通过 LocalKBAdapter 接入，无需额外配置。
            </Text>
          </Space>
        </>
      )}
    </Modal>
  );
};

export default AdapterRegistrationModal;
