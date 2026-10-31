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
import { ProviderConfigCard } from "./ProviderConfigCard";
import {
  loadMemoryConfig,
  setExternalProviderTopK,
  setMemorySwitch,
  subscribeMemorySwitch,
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
  { labelKey: string; descriptionKey: string; icon: typeof Building2 }
> = {
  tenant: {
    labelKey: "memory.longTerm.scope.tenant",
    descriptionKey: "memory.scope.tenant.description",
    icon: Building2,
  },
  user: {
    labelKey: "memory.longTerm.scope.user",
    descriptionKey: "memory.scope.user.description",
    icon: UserRound,
  },
  agent: {
    labelKey: "memory.longTerm.scope.agent",
    descriptionKey: "memory.scope.agent.description",
    icon: Bot,
  },
};

const typeMap: Record<MemoryType, { labelKey: string; color: string }> = {
  long_term: { labelKey: "memory.type.long_term", color: "blue" },
  short_term: { labelKey: "memory.type.short_term", color: "default" },
};

const statusMap: Record<MemoryStatus, { labelKey: string; color: string }> = {
  active: { labelKey: "memory.status.active", color: "green" },
  archived: { labelKey: "memory.status.archived", color: "default" },
  disabled: { labelKey: "memory.status.disabled", color: "orange" },
};

const defaultConfig: MemoryConfig = {
  memoryEnabled: true,
  shareOption: "always",
  disableAgentIds: [],
  disableUserAgentIds: [],
  externalProviderTopK: 20,
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
          message.warning(t("memory.manager.refreshPartialFail"));
        }
      } catch {
        message.error(t("memory.manager.loadListFailed"));
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
      { value: "all", label: t("memory.manager.agentFilter.all") },
      ...Array.from(options, ([value, label]) => ({ value, label })),
    ];
  }, [recordsByScope.agent, t]);

  const conversationOptions = useMemo(() => {
    const options = new Map<string, string>();
    recordsByScope.agent.forEach((record) => {
      if (record.conversation_id) {
        options.set(
          record.conversation_id,
          record.conversation_title ||
            t("memory.manager.conversationFallback", {
              id: record.conversation_id,
            })
        );
      }
    });
    return [
      { value: "all", label: t("memory.manager.conversationFilter.all") },
      ...Array.from(options, ([value, label]) => ({ value, label })),
    ];
  }, [recordsByScope.agent, t]);

  useEffect(() => {
    return subscribeMemorySwitch((enabled) => {
      setConfig((current) => ({ ...current, memoryEnabled: enabled }));
    });
  }, []);

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
        message.success(t("memory.manager.updateSuccess"));
      } else {
        await createMemoryRecord({
          layer: scope,
          memory_type: "long_term",
          content: values.content,
        });
        message.success(t("memory.manager.createSuccess"));
      }
      setEditorOpen(false);
      await refreshRecords(scope);
    } catch {
      message.error(
        editing
          ? t("memory.manager.updateFailed")
          : t("memory.manager.createFailed")
      );
    }
  };

  const confirmDelete = (record: MemoryRecord) => {
    if (!scope) return;
    const targetScope = scope;
    modal.confirm({
      centered: true,
      title: t("memory.manager.deleteConfirmTitle"),
      content: t("memory.manager.deleteConfirmContent"),
      okText: t("memory.manager.deleteConfirmOk"),
      cancelText: t("memory.manager.cancel"),
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
          message.success(t("memory.manager.deleteSuccess"));
        } catch {
          message.error(t("memory.manager.deleteFailed"));
        }
      },
    });
  };

  const columns: TableProps<MemoryRecord>["columns"] = [
    {
      title: t("memory.manager.field.content"),
      dataIndex: "content",
      key: "content",
      render: (content: string) => (
        <Paragraph
          className="memory-content"
          ellipsis={{
            rows: 2,
            expandable: true,
            symbol: t("memory.manager.column.expand"),
          }}
        >
          {content}
        </Paragraph>
      ),
    },
    ...(scope === "agent"
      ? [
          {
            title: t("memory.manager.column.agentName"),
            dataIndex: "agent_name",
            key: "agent_name",
            width: 160,
            render: (value: string | null, record: MemoryRecord) =>
              value || (record.agent_id ? `Agent ${record.agent_id}` : "-"),
          },
          {
            title: t("memory.manager.column.conversation"),
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
                  {value ||
                    t("memory.manager.conversationFallback", {
                      id: record.conversation_id,
                    })}
                </Link>
              ) : (
                "-"
              ),
          },
        ]
      : []),
    {
      title: t("memory.manager.field.type"),
      dataIndex: "memory_type",
      key: "memory_type",
      width: 130,
      render: (value: MemoryType) => (
        <Tag color={typeMap[value]?.color}>
          {typeMap[value]
            ? t(typeMap[value].labelKey)
            : value}
        </Tag>
      ),
    },
    {
      title: t("memory.manager.field.status"),
      dataIndex: "status",
      key: "status",
      width: 110,
      render: (value: MemoryStatus) => (
        <Tag color={statusMap[value]?.color}>
          {statusMap[value]
            ? t(statusMap[value].labelKey)
            : value}
        </Tag>
      ),
    },
    {
      title: t("memory.manager.column.createTime"),
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
      title: t("memory.manager.column.actions"),
      key: "actions",
      align: "right",
      width: scope === "agent" ? 72 : 112,
      render: (_, record) => (
        <Space size={4}>
          <Tooltip
            title={
              scope === "agent" && record.embedding_compatible === false
                ? t("memory.manager.editIncompatibleTooltip")
                : t("memory.manager.editTooltip")
            }
          >
            <Button
              type="text"
              aria-label={t("memory.manager.editAriaLabel")}
              icon={<Edit3 size={17} />}
              disabled={
                scope === "agent" && record.embedding_compatible === false
              }
              onClick={() => openEdit(record)}
            />
          </Tooltip>
          <Tooltip title={t("memory.manager.deleteTooltip")}>
            <Button
              type="text"
              danger
              aria-label={t("memory.manager.deleteAriaLabel")}
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
      <Flex vertical gap={24} className="memory-config-stack">
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
        <ProviderConfigCard
          memoryEnabled={config.memoryEnabled}
          topK={config.externalProviderTopK}
          savingTopK={savingConfig}
          onTopKChange={(value) =>
            setConfig((current) => ({
              ...current,
              externalProviderTopK: value,
            }))
          }
          onTopKSave={async () => {
            setSavingConfig(true);
            try {
              await setExternalProviderTopK(config.externalProviderTopK);
            } finally {
              setSavingConfig(false);
            }
          }}
        />
      </Flex>
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
            <Title level={4}>
              {t("memory.manager.scopeTitle", { scope: t(meta.labelKey) })}
            </Title>
            <Text type="secondary">{t(meta.descriptionKey)}</Text>
          </div>
          {scope === "user" && (
            <Button
              type="primary"
              icon={<Plus size={17} />}
              onClick={openCreate}
            >
              {t("memory.manager.createButton")}
            </Button>
          )}
          {scope === "tenant" && (
            <Can permission="mem.tenant:create">
              <Button
                type="primary"
                icon={<Plus size={17} />}
                onClick={openCreate}
              >
                {t("memory.manager.createButton")}
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
            placeholder={t("memory.manager.searchPlaceholder")}
            className="search-input"
          />
          <Select
            aria-label={t("memory.manager.statusFilterAria")}
            value={statusFilter}
            onChange={setStatusFilter}
            className="status-select"
            options={[
              { value: "all", label: t("memory.manager.statusFilterAll") },
              ...Object.entries(statusMap).map(([value, meta]) => ({
                value,
                label: t(meta.labelKey),
              })),
            ]}
          />
          {scope === "agent" && (
            <>
              <Select
                aria-label={t("memory.manager.agentFilterAria")}
                value={agentFilter}
                onChange={setAgentFilter}
                className="agent-select"
                options={agentOptions}
                showSearch
                optionFilterProp="label"
              />
              <Select
                aria-label={t("memory.manager.conversationFilterAria")}
                value={conversationFilter}
                onChange={setConversationFilter}
                className="conversation-select"
                options={conversationOptions}
                showSearch
                optionFilterProp="label"
              />
              <DatePicker.RangePicker
                aria-label={t("memory.manager.createdRangeAria")}
                value={createdRange}
                onChange={(dates) => setCreatedRange(dates)}
                className="created-range-picker"
                placeholder={[
                  t("memory.manager.createdRangeStart"),
                  t("memory.manager.createdRangeEnd"),
                ]}
              />
            </>
          )}
          <Text type="secondary" className="result-count">
            {t("memory.manager.resultCount", { count: visibleRecords.length })}
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
              t("memory.manager.paginationTotal", {
                start: range[0],
                end: range[1],
                total,
              }),
            position: ["bottomRight"],
          }}
          scroll={{ x: scope === "agent" ? 1180 : 780 }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("memory.manager.emptyText")}
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
        title={
          editing
            ? t("memory.manager.editor.title.edit")
            : t("memory.manager.editor.title.create")
        }
        okText={
          editing
            ? t("memory.manager.editor.ok.edit")
            : t("memory.manager.editor.ok.create")
        }
        cancelText={t("memory.manager.cancel")}
        onOk={saveMemory}
        onCancel={() => setEditorOpen(false)}
        destroyOnHidden
        forceRender
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
              label={t("memory.manager.field.type")}
              rules={[{ required: true }]}
              className="form-half"
            >
              <Select
                options={Object.entries(typeMap)
                  .filter(([value]) => !(!editing && value !== "long_term"))
                  .map(([value, meta]) => ({
                    value,
                    label: t(meta.labelKey),
                  }))}
              />
            </Form.Item>
            <Form.Item
              name="status"
              label={t("memory.manager.field.status")}
              rules={[{ required: true }]}
              className="form-half"
            >
              <Select
                options={Object.entries(statusMap).map(([value, meta]) => ({
                  value,
                  label: t(meta.labelKey),
                }))}
              />
            </Form.Item>
          </Flex>
          <Form.Item
            name="content"
            label={t("memory.manager.field.content")}
            rules={[
              {
                required: true,
                whitespace: true,
                message: t("memory.manager.form.contentRequired"),
              },
              {
                max: 500,
                message: t("memory.manager.form.contentMax"),
              },
            ]}
          >
            <Input.TextArea
              rows={6}
              showCount
              maxLength={500}
              placeholder={t("memory.manager.form.contentPlaceholder")}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
