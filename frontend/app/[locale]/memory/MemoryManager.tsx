"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Card,
  DatePicker,
  Empty,
  Flex,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  type TableProps,
} from "antd";
import type { Dayjs } from "dayjs";
import {
  Bot,
  Building2,
  Clock3,
  Edit3,
  Plus,
  Search,
  Settings,
  Trash2,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { useTranslation } from "react-i18next";

import { Can } from "@/components/permission/Can";
import { DreamingConfigCards } from "./DreamingConfigCards";
import { LongTermMemoryPanel } from "./LongTermMemoryPanel";
import {
  loadMemoryConfig,
  setMemorySwitch,
  type MemoryConfig,
} from "@/services/memoryService";
import {
  createMemoryRecord,
  deleteMemoryRecord,
  listMemoryRecords,
  synchronizeMemoryRecordStatuses,
  updateMemoryRecord,
  type MemoryRecord,
  type MemoryScope,
  type MemoryStatus,
  type MemoryType,
} from "@/services/memoryRecordService";

const { Text, Title, Paragraph } = Typography;

type TabKey = "base" | MemoryScope;
type MemoryForm = {
  memory_type: MemoryType;
  status: MemoryStatus;
  content: string;
};

const scopeMeta: Record<
  MemoryScope,
  { labelKey: string; description: string; icon: typeof Building2 }
> = {
  tenant: {
    labelKey: "memory.longTerm.scope.tenant",
    description: "组织范围内共享的全局记忆",
    icon: Building2,
  },
  user: {
    labelKey: "memory.longTerm.scope.user",
    description: "与当前用户偏好相关的记忆",
    icon: UserRound,
  },
  agent: {
    labelKey: "memory.longTerm.scope.agent",
    description: "由智能体运行过程生成的记忆",
    icon: Bot,
  },
};

const typeMap: Record<MemoryType, { label: string; color: string }> = {
  long_term: { label: "长期记忆", color: "blue" },
  short_term: { label: "短期记忆", color: "default" },
};

const statusMap: Record<MemoryStatus, { label: string; color: string }> = {
  active: { label: "生效中", color: "green" },
  archived: { label: "已归档", color: "default" },
  disabled: { label: "已停用", color: "orange" },
};

const defaultConfig: MemoryConfig = {
  memoryEnabled: true,
  shareOption: "always",
  disableAgentIds: [],
  disableUserAgentIds: [],
};

const memoryScopes = Object.keys(scopeMeta) as MemoryScope[];

const emptyRecordsByScope = (): Record<MemoryScope, MemoryRecord[]> => ({
  tenant: [],
  user: [],
  agent: [],
});

const initialLoadingByScope: Record<MemoryScope, boolean> = {
  tenant: true,
  user: true,
  agent: true,
};

export function MemoryManager() {
  const { message, modal } = App.useApp();
  const { t } = useTranslation("common");
  const [activeTab, setActiveTab] = useState<TabKey>("base");
  const [recordsByScope, setRecordsByScope] = useState(emptyRecordsByScope);
  const [config, setConfig] = useState<MemoryConfig>(defaultConfig);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [agentFilter, setAgentFilter] = useState("all");
  const [conversationFilter, setConversationFilter] = useState("all");
  const [createdRange, setCreatedRange] = useState<
    [Dayjs | null, Dayjs | null] | null
  >(null);
  const [loadingByScope, setLoadingByScope] = useState(initialLoadingByScope);
  const [configLoading, setConfigLoading] = useState(true);
  const [savingConfig, setSavingConfig] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<MemoryRecord | null>(null);
  const [form] = Form.useForm<MemoryForm>();

  const scope = activeTab === "base" ? null : activeTab;
  const records = scope ? recordsByScope[scope] : [];

  const refreshRecords = useCallback(
    async (targetScope: MemoryScope) => {
      setLoadingByScope((current) => ({ ...current, [targetScope]: true }));
      try {
        const nextRecords = await listMemoryRecords(targetScope);
        const syncResult = await synchronizeMemoryRecordStatuses(nextRecords);
        setRecordsByScope((current) => ({
          ...current,
          [targetScope]: syncResult.records,
        }));
        if (syncResult.failedCount > 0) {
          message.warning("部分记忆状态同步失败，请稍后重试");
        }
      } catch {
        message.error("记忆列表加载失败");
      } finally {
        setLoadingByScope((current) => ({
          ...current,
          [targetScope]: false,
        }));
      }
    },
    [message]
  );

  useEffect(() => {
    let active = true;
    loadMemoryConfig()
      .then((nextConfig) => {
        if (active) setConfig(nextConfig);
      })
      .finally(() => {
        if (active) setConfigLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    void refreshRecords("agent");
  }, [refreshRecords]);

  const visibleRecords = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return records.filter((record) => {
      const matchesQuery = record.content
        .toLowerCase()
        .includes(normalizedQuery);
      const matchesStatus =
        statusFilter === "all" || record.status === statusFilter;
      const matchesAgent =
        scope !== "agent" ||
        agentFilter === "all" ||
        record.agent_id === agentFilter;
      const matchesConversation =
        scope !== "agent" ||
        conversationFilter === "all" ||
        record.conversation_id === conversationFilter;
      const createdAt = record.create_time
        ? new Date(record.create_time).getTime()
        : null;
      const matchesCreatedRange =
        scope !== "agent" ||
        !createdRange ||
        !createdRange[0] ||
        !createdRange[1] ||
        (createdAt !== null &&
          createdAt >= createdRange[0].startOf("day").valueOf() &&
          createdAt <= createdRange[1].endOf("day").valueOf());
      return (
        matchesQuery &&
        matchesStatus &&
        matchesAgent &&
        matchesConversation &&
        matchesCreatedRange
      );
    });
  }, [
    agentFilter,
    conversationFilter,
    createdRange,
    query,
    records,
    scope,
    statusFilter,
  ]);

  const agentOptions = useMemo(() => {
    const options = new Map<string, string>();
    recordsByScope.agent.forEach((record) => {
      if (record.agent_id) {
        options.set(
          record.agent_id,
          record.agent_name || `Agent ${record.agent_id}`
        );
      }
    });
    return [
      { value: "all", label: "全部智能体" },
      ...Array.from(options, ([value, label]) => ({ value, label })),
    ];
  }, [recordsByScope.agent]);

  const conversationOptions = useMemo(() => {
    const options = new Map<string, string>();
    recordsByScope.agent.forEach((record) => {
      if (record.conversation_id) {
        options.set(
          record.conversation_id,
          record.conversation_title || `会话 ${record.conversation_id}`
        );
      }
    });
    return [
      { value: "all", label: "全部会话" },
      ...Array.from(options, ([value, label]) => ({ value, label })),
    ];
  }, [recordsByScope.agent]);

  const updateMemoryEnabled = async (enabled: boolean) => {
    const previous = config.memoryEnabled;
    setConfig((current) => ({ ...current, memoryEnabled: enabled }));
    setSavingConfig(true);
    const saved = await setMemorySwitch(enabled);
    setSavingConfig(false);
    if (!saved) {
      setConfig((current) => ({ ...current, memoryEnabled: previous }));
      message.error(t("useMemory.setMemorySwitchError"));
    }
  };

  const openCreate = () => {
    if (!scope || scope === "agent") return;
    setEditing(null);
    form.setFieldsValue({
      memory_type: "long_term",
      status: "active",
      content: "",
    });
    setEditorOpen(true);
  };

  const openEdit = (record: MemoryRecord) => {
    if (scope === "agent" && record.embedding_compatible === false) {
      return;
    }
    setEditing(record);
    form.setFieldsValue({
      memory_type: record.memory_type,
      status: record.status,
      content: record.content,
    });
    setEditorOpen(true);
  };

  const saveMemory = async () => {
    if (!scope) return;
    const values = await form.validateFields();
    try {
      if (editing) {
        await updateMemoryRecord(editing.memory_id, {
          content: values.content,
          status: values.status,
        });
        message.success("记忆已更新");
      } else {
        await createMemoryRecord({
          layer: scope,
          memory_type: "long_term",
          content: values.content,
        });
        message.success("记忆已创建");
      }
      setEditorOpen(false);
      await refreshRecords(scope);
    } catch {
      message.error(editing ? "记忆更新失败" : "记忆创建失败");
    }
  };

  const confirmDelete = (record: MemoryRecord) => {
    if (!scope) return;
    const targetScope = scope;
    modal.confirm({
      centered: true,
      title: "删除这条记忆？",
      content: "删除后将无法恢复，请确认是否继续。",
      okText: "确认删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deleteMemoryRecord(record.memory_id);
          setRecordsByScope((current) => ({
            ...current,
            [targetScope]: current[targetScope].filter(
              (item) => item.memory_id !== record.memory_id
            ),
          }));
          message.success("记忆已删除");
        } catch {
          message.error("记忆删除失败");
        }
      },
    });
  };

  const columns: TableProps<MemoryRecord>["columns"] = [
    {
      title: "记忆内容",
      dataIndex: "content",
      key: "content",
      render: (content: string) => (
        <Paragraph
          className="memory-content"
          ellipsis={{ rows: 2, expandable: true, symbol: "展开" }}
        >
          {content}
        </Paragraph>
      ),
    },
    ...(scope === "agent"
      ? [
          {
            title: "智能体名称",
            dataIndex: "agent_name",
            key: "agent_name",
            width: 160,
            render: (value: string | null, record: MemoryRecord) =>
              value || (record.agent_id ? `Agent ${record.agent_id}` : "-"),
          },
          {
            title: "来源对话",
            dataIndex: "conversation_title",
            key: "conversation_title",
            width: 200,
            render: (value: string | null, record: MemoryRecord) =>
              record.conversation_id ? (
                <Link
                  href={`/newchat?thread_id=${encodeURIComponent(
                    record.conversation_id
                  )}`}
                  className="memory-conversation-link"
                >
                  {value || `会话 ${record.conversation_id}`}
                </Link>
              ) : (
                "-"
              ),
          },
        ]
      : []),
    {
      title: "记忆类型",
      dataIndex: "memory_type",
      key: "memory_type",
      width: 130,
      render: (value: MemoryType) => (
        <Tag color={typeMap[value]?.color}>
          {typeMap[value]?.label ?? value}
        </Tag>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 110,
      render: (value: MemoryStatus) => (
        <Tag color={statusMap[value]?.color}>
          {statusMap[value]?.label ?? value}
        </Tag>
      ),
    },
    {
      title: "创建时间",
      dataIndex: "create_time",
      key: "create_time",
      width: 190,
      render: (value: string | null) => (
        <span className="memory-time">
          <Clock3 size={15} aria-hidden="true" />
          {value ? new Date(value).toLocaleString() : "-"}
        </span>
      ),
    },
    {
      title: "操作",
      key: "actions",
      align: "right",
      width: scope === "agent" ? 72 : 112,
      render: (_, record) => (
        <Space size={4}>
          <Tooltip
            title={
              scope === "agent" && record.embedding_compatible === false
                ? "当前向量模型与该记忆不兼容，无法编辑"
                : "编辑"
            }
          >
            <Button
              type="text"
              aria-label="编辑记忆"
              icon={<Edit3 size={17} />}
              disabled={
                scope === "agent" && record.embedding_compatible === false
              }
              onClick={() => openEdit(record)}
            />
          </Tooltip>
          <Tooltip title="删除">
            <Button
              type="text"
              danger
              aria-label="删除记忆"
              icon={<Trash2 size={17} />}
              onClick={() => confirmDelete(record)}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  const renderBaseSettings = () => (
    <div className="memory-config-content">
      <Title level={4}>{t("memoryManageModal.baseSettings")}</Title>
      <Text type="secondary">
        {t("memoryManageModal.baseSettingsDescription")}
      </Text>
      <Card className="memory-config-card" loading={configLoading}>
        <Flex align="center" justify="space-between" gap={24}>
          <Flex align="center" gap={12}>
            <Settings size={20} />
            <div>
              <Text strong>{t("memoryManageModal.memoryAbility")}</Text>
              <Text type="secondary" className="memory-setting-description">
                {t("memoryManageModal.memoryAbilityDescription")}
              </Text>
            </div>
          </Flex>
          <Switch
            checked={config.memoryEnabled}
            loading={savingConfig}
            onChange={updateMemoryEnabled}
          />
        </Flex>
      </Card>
      <DreamingConfigCards />
    </div>
  );

  const renderRecordTable = () => {
    if (!scope) return null;
    const meta = scopeMeta[scope];
    return (
      <div className="panel-body">
        <Flex
          align="center"
          justify="space-between"
          gap={16}
          wrap="wrap"
          className="scope-intro"
        >
          <div>
            <Title level={4}>{t(meta.labelKey)} 记忆</Title>
            <Text type="secondary">{meta.description}</Text>
          </div>
          {scope === "user" && (
            <Button
              type="primary"
              icon={<Plus size={17} />}
              onClick={openCreate}
            >
              新建记忆
            </Button>
          )}
          {scope === "tenant" && (
            <Can permission="mem.tenant:create">
              <Button
                type="primary"
                icon={<Plus size={17} />}
                onClick={openCreate}
              >
                新建记忆
              </Button>
            </Can>
          )}
        </Flex>

        <Flex gap={12} wrap="wrap" className="memory-toolbar">
          <Input
            allowClear
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            prefix={<Search size={17} aria-hidden="true" />}
            placeholder="搜索记忆内容"
            className="search-input"
          />
          <Select
            aria-label="按状态筛选"
            value={statusFilter}
            onChange={setStatusFilter}
            className="status-select"
            options={[
              { value: "all", label: "全部状态" },
              ...Object.entries(statusMap).map(([value, meta]) => ({
                value,
                label: meta.label,
              })),
            ]}
          />
          {scope === "agent" && (
            <>
              <Select
                aria-label="按智能体筛选"
                value={agentFilter}
                onChange={setAgentFilter}
                className="agent-select"
                options={agentOptions}
                showSearch
                optionFilterProp="label"
              />
              <Select
                aria-label="按来源对话筛选"
                value={conversationFilter}
                onChange={setConversationFilter}
                className="conversation-select"
                options={conversationOptions}
                showSearch
                optionFilterProp="label"
              />
              <DatePicker.RangePicker
                aria-label="按创建时间段筛选"
                value={createdRange}
                onChange={(dates) => setCreatedRange(dates)}
                className="created-range-picker"
                placeholder={["开始日期", "结束日期"]}
              />
            </>
          )}
          <Text type="secondary" className="result-count">
            共 {visibleRecords.length} 条记忆
          </Text>
        </Flex>

        <Table<MemoryRecord>
          rowKey="memory_id"
          loading={loadingByScope[scope]}
          columns={columns}
          dataSource={visibleRecords}
          rowClassName={(record) =>
            scope === "agent" && record.embedding_compatible === false
              ? "memory-row-incompatible"
              : ""
          }
          pagination={{
            defaultPageSize: 10,
            pageSizeOptions: [10, 20, 50],
            showSizeChanger: true,
            showTotal: (total, range) =>
              `第 ${range[0]}–${range[1]} 条，共 ${total} 条`,
            position: ["bottomRight"],
          }}
          scroll={{ x: scope === "agent" ? 1180 : 780 }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无符合条件的记忆"
              />
            ),
          }}
        />
      </div>
    );
  };

  return (
    <div
      className={`memory-panel ${
        activeTab === "tenant" || activeTab === "user"
          ? "memory-panel-long-term"
          : ""
      }`}
    >
      <Tabs
        activeKey={activeTab}
        onChange={(key) => {
          setActiveTab(key as TabKey);
          setQuery("");
          setStatusFilter("all");
          setAgentFilter("all");
          setConversationFilter("all");
          setCreatedRange(null);
        }}
        items={[
          {
            key: "base",
            label: (
              <span className="tab-label">
                <Settings size={17} />
                {t("memoryManageModal.baseSettings")}
              </span>
            ),
          },
          ...memoryScopes.map((key) => {
            const Icon = scopeMeta[key].icon;
            return {
              key,
              label: (
                <span className="tab-label">
                  <Icon size={17} aria-hidden="true" />
                  {t(scopeMeta[key].labelKey)}
                  {key === "agent" && (
                    <span className="tab-count">
                      {loadingByScope.agent ? "…" : recordsByScope.agent.length}
                    </span>
                  )}
                </span>
              ),
            };
          }),
        ]}
      />
      {activeTab === "base" ? (
        renderBaseSettings()
      ) : activeTab === "tenant" || activeTab === "user" ? (
        <LongTermMemoryPanel scope={activeTab} />
      ) : (
        renderRecordTable()
      )}

      <Modal
        open={editorOpen}
        centered
        title={editing ? "编辑记忆" : "新建记忆"}
        okText={editing ? "保存修改" : "创建记忆"}
        cancelText="取消"
        onOk={saveMemory}
        onCancel={() => setEditorOpen(false)}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          requiredMark={false}
          className="memory-form"
        >
          <Flex gap={12}>
            <Form.Item
              name="memory_type"
              label="记忆类型"
              rules={[{ required: true }]}
              className="form-half"
            >
              <Select
                options={Object.entries(typeMap)
                  .filter(([value]) => !(!editing && value !== "long_term"))
                  .map(([value, meta]) => ({
                    value,
                    label: meta.label,
                  }))}
              />
            </Form.Item>
            <Form.Item
              name="status"
              label="状态"
              rules={[{ required: true }]}
              className="form-half"
            >
              <Select
                options={Object.entries(statusMap).map(([value, meta]) => ({
                  value,
                  label: meta.label,
                }))}
              />
            </Form.Item>
          </Flex>
          <Form.Item
            name="content"
            label="记忆内容"
            rules={[
              { required: true, whitespace: true, message: "请输入记忆内容" },
              { max: 500, message: "最多输入 500 个字符" },
            ]}
          >
            <Input.TextArea
              rows={6}
              showCount
              maxLength={500}
              placeholder="输入希望被记住的信息…"
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
