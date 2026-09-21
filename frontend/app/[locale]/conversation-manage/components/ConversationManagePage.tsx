"use client";

import { useCallback, useMemo, useState } from "react";
import {
  Button,
  DatePicker,
  Empty,
  Flex,
  Form,
  Input,
  Modal,
  Select,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
  type TableProps,
} from "antd";
import type { Dayjs } from "dayjs";
import {
  Clock3,
  Search,
  Eye,
  RotateCcw,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";

import { useConversationManage } from "@/hooks/chat/useConversationManage";
import { useAgentList } from "@/hooks/agent/useAgentList";
import { conversationService } from "@/services/conversationService";
import { ApiConversationDetail, ApiConversationResponse } from "@/types/conversation";

const { Text } = Typography;

interface ConversationManagePageProps {
  className?: string;
}

interface ConversationDetail {
  message?: Array<{
    role?: string;
    message?: string | Array<{ content?: string }>;
    create_time?: number | null;
  }>;
}

interface MessageItem {
  role?: string;
  message?: string | Array<{ content?: string }>;
  create_time?: number | null;
}

export function ConversationManagePage({ className = "" }: ConversationManagePageProps) {
  const { t } = useTranslation("common");

  const {
    conversationList,
    isLoading,
    total,
    refetch,
    filters,
    setFilters,
    resetFilters,
  } = useConversationManage();

  const { agents: allAgents, isLoading: agentsLoading } = useAgentList("");

  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [selectedConversation, setSelectedConversation] = useState<typeof conversationList[0] | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [conversationDetail, setConversationDetail] = useState<ConversationDetail | null>(null);

  const createdRange = useMemo<[Dayjs | null, Dayjs | null] | null>(() => {
    if (filters.startDateMs || filters.endDateMs) {
      const start = filters.startDateMs ? dayjs(filters.startDateMs) : null;
      const end = filters.endDateMs ? dayjs(filters.endDateMs) : null;
      return [start, end];
    }
    return null;
  }, [filters.startDateMs, filters.endDateMs]);

  const onDateRangeChange = useCallback(
    (dates: [Dayjs | null, Dayjs | null] | null) => {
      if (dates) {
        const [start, end] = dates;
        setFilters((prev) => ({
          ...prev,
          startDateMs: start ? start.startOf("day").valueOf() : undefined,
          endDateMs: end ? end.endOf("day").valueOf() : undefined,
        }));
      } else {
        setFilters((prev) => ({
          ...prev,
          startDateMs: undefined,
          endDateMs: undefined,
        }));
      }
    },
    [setFilters]
  );

  const handleSearch = useCallback(() => {
    refetch();
  }, [refetch]);

  const handleReset = useCallback(() => {
    resetFilters();
  }, [resetFilters]);

  const openDetail = useCallback(async (conversation: typeof conversationList[0]) => {
    setSelectedConversation(conversation);
    setDetailLoading(true);
    setConversationDetail(null);
    setDetailModalOpen(true);
    try {
      const response = await conversationService.getDetail(conversation.conversation_id);
      // conversationService.getDetail returns ApiConversationResponse: { code, data: ApiConversationDetail[], message }
      const detail = (response as ApiConversationResponse).data?.[0] as ApiConversationDetail | undefined;
      const convertedDetail: ConversationDetail = {
        message: detail?.message,
      };
      setConversationDetail(convertedDetail);
    } catch (e) {
      console.error("Failed to load conversation detail:", e);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const closeDetail = useCallback(() => {
    setDetailModalOpen(false);
    setSelectedConversation(null);
    setConversationDetail(null);
  }, []);

  const agentOptions = useMemo(() => {
    return [
      { value: "all", label: t("conversationManage.allAgents") },
      ...allAgents.map((agent: { agent_id: number; name?: string }) => ({
        value: String(agent.agent_id),
        label: agent.name || `Agent ${agent.agent_id}`,
      })),
    ];
  }, [allAgents, t]);

  const columns: TableProps<typeof conversationList[0]>["columns"] = useMemo(
    () => [
      {
        title: t("conversationManage.title"),
        dataIndex: "conversation_title",
        key: "conversation_title",
        width: 300,
        ellipsis: true,
      },
      {
        title: t("conversationManage.agent"),
        dataIndex: "agent_id",
        key: "agent_id",
        width: 180,
        render: (agentId: number | null | undefined) =>
          agentId ? `Agent ${agentId}` : t("conversationManage.noAgent"),
      },
      {
        title: t("conversationManage.createTime"),
        dataIndex: "create_time",
        key: "create_time",
        width: 200,
        render: (createTime: number) => (
          <span>
            <Clock3 size={15} aria-hidden="true" />
            {dayjs(createTime).format("YYYY-MM-DD HH:mm:ss")}
          </span>
        ),
      },
      {
        title: t("conversationManage.updateTime"),
        dataIndex: "update_time",
        key: "update_time",
        width: 200,
        render: (updateTime: number) => (
          <span>
            <Clock3 size={15} aria-hidden="true" />
            {dayjs(updateTime).format("YYYY-MM-DD HH:mm:ss")}
          </span>
        ),
      },
      {
        title: t("conversationManage.actions"),
        key: "actions",
        align: "center",
        width: 100,
        render: (_, record) => (
          <Tooltip title={t("conversationManage.viewDetail")}>
            <Button
              type="text"
              icon={<Eye size={17} />}
              onClick={() => openDetail(record)}
              disabled={detailLoading}
            />
          </Tooltip>
        ),
      },
    ],
    [t, detailLoading, openDetail]
  );

  const hasActiveFilters = useMemo(
    () =>
      filters.startDateMs !== undefined ||
      filters.endDateMs !== undefined ||
      (filters.agentId !== undefined && filters.agentId !== null) ||
      (filters.keyword !== undefined && filters.keyword.trim() !== ""),
    [filters]
  );

  return (
    <div className={`conversation-manage-page ${className}`}>
      <div className="conversation-manage-toolbar">
        <Form layout="inline" onFinish={handleSearch}>
          <Form.Item name="keyword" label={t("conversationManage.keyword")}>
            <Input
              allowClear
              placeholder={t("conversationManage.keywordPlaceholder")}
              prefix={<Search size={17} aria-hidden="true" />}
              value={filters.keyword}
              onChange={(e) =>
                setFilters((prev) => ({ ...prev, keyword: e.target.value }))
              }
              style={{ width: 240 }}
            />
          </Form.Item>

          <Form.Item name="agentId" label={t("conversationManage.agent")}>
            <Select
              showSearch
              optionFilterProp="label"
              value={filters.agentId ? String(filters.agentId) : "all"}
              onChange={(value) =>
                setFilters((prev) => ({
                  ...prev,
                  agentId: value === "all" ? null : Number(value),
                }))
              }
              options={agentOptions}
              style={{ width: 200 }}
              disabled={agentsLoading}
            />
          </Form.Item>

          <Form.Item name="dateRange" label={t("conversationManage.dateRange")}>
            <DatePicker.RangePicker
              value={createdRange}
              onChange={onDateRangeChange}
              placeholder={[
                t("conversationManage.startDate"),
                t("conversationManage.endDate"),
              ]}
              style={{ width: 300 }}
            />
          </Form.Item>

          <Form.Item>
            <Flex gap={8}>
              <Button type="primary" htmlType="submit" icon={<Search size={17} />} loading={isLoading}>
                {t("conversationManage.search")}
              </Button>
              <Button onClick={handleReset} icon={<RotateCcw size={17} />}>
                {t("conversationManage.reset")}
              </Button>
            </Flex>
          </Form.Item>

          <Form.Item>
            <Text type="secondary" className="result-count">
              {t("conversationManage.totalCount", { total })}
            </Text>
          </Form.Item>
        </Form>
      </div>

      <Table<typeof conversationList[0]>
        rowKey="conversation_id"
        loading={isLoading}
        columns={columns}
        dataSource={conversationList}
        pagination={{
          defaultPageSize: 20,
          pageSizeOptions: [10, 20, 50],
          showSizeChanger: true,
          showTotal: (totalCount, range) =>
            t("conversationManage.pageRange", {
              start: range[0],
              end: range[1],
              total: totalCount,
            }),
          position: ["bottomRight"],
        }}
        scroll={{ x: 980 }}
        locale={{
          emptyText: (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                hasActiveFilters
                  ? t("conversationManage.noResults")
                  : t("conversationManage.noData")
              }
            />
          ),
        }}
      />

      <Modal
        open={detailModalOpen}
        centered
        title={selectedConversation?.conversation_title || t("conversationManage.detailTitle")}
        onCancel={closeDetail}
        destroyOnHidden
        forceRender
        width={800}
        footer={null}
      >
        {detailLoading ? (
          <Flex vertical style={{ padding: 48, alignItems: "center" }}>
            <Spin size="large" />
            <Text type="secondary" style={{ marginTop: 16 }}>
              {t("conversationManage.loadingDetail")}
            </Text>
          </Flex>
        ) : conversationDetail ? (
          <div className="conversation-detail-content" style={{ maxHeight: "60vh", overflow: "auto" }}>
            {conversationDetail.message?.map((msg: MessageItem, idx: number) => (
              <div key={idx} style={{ marginBottom: 24, padding: 16, borderRadius: 8, background: "#fafafa" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <Tag color={msg.role === "user" ? "blue" : "green"}>
                    {msg.role === "user" ? t("conversationManage.user") : t("conversationManage.assistant")}
                  </Tag>
                  {msg.create_time && (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {dayjs(msg.create_time).format("YYYY-MM-DD HH:mm:ss")}
                    </Text>
                  )}
                </div>
                <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                  {Array.isArray(msg.message)
                    ? msg.message
                        .map((m) => (typeof m === "string" ? m : m.content))
                        .join("\n")
                    : String(msg.message)}
                </div>
              </div>
            ))}
            {!conversationDetail.message?.length && (
              <Flex vertical style={{ padding: 48, alignItems: "center" }}>
                <Text type="secondary">{t("conversationManage.noMessages")}</Text>
              </Flex>
            )}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}