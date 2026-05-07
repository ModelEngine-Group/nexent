"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import {
  Modal,
  Button,
  Input,
  Form,
  Tabs,
  Table,
  Tag,
  Space,
  Typography,
  Card,
  Tooltip,
  message,
  Select,
  Popover,
  Radio,
} from "antd";
import {
  Globe,
  RefreshCw,
  Trash2,
  Plus,
  CheckCircle,
  XCircle,
  AlertCircle,
  ExternalLink,
  Search,
  Eye,
  Settings,
  MessageCircle,
} from "lucide-react";
import { a2aClientService, A2AExternalAgent } from "@/services/a2aService";
import A2AChatModal from "./A2AChatModal";
import NacosDiscoveryPanel from "./NacosDiscoveryPanel";
import log from "@/lib/logger";

const { Text, Title } = Typography;

// Protocol type constants
const PROTOCOL_TYPES = [
  { value: "JSONRPC", label: "JSONRPC" },
  { value: "HTTP+JSON", label: "HTTP+JSON" },
  { value: "GRPC", label: "GRPC", disabled: true },
];

// Protocol binding to protocol type mapping
const PROTOCOL_BINDING_MAP: Record<string, string> = {
  "http-json-rpc": "JSONRPC",
  "jsonrpc": "JSONRPC",
  "httpjsonrpc": "JSONRPC",
  "httprest": "HTTP+JSON",
  "rest": "HTTP+JSON",
  "http+json": "HTTP+JSON",
  "grpc": "GRPC",
};

interface A2AAgentDiscoveryModalProps {
  open: boolean;
  onClose: () => void;
  onAgentDiscovered?: (agent: A2AExternalAgent) => void;
  onDiscoverSuccess?: () => void;
  nacosConfigId?: string;
  localAgentId?: number;
}

// Helper function to extract available protocols from supported interfaces
function extractAvailableProtocols(supportedInterfaces?: Record<string, any>[]): string[] {
  if (!supportedInterfaces || supportedInterfaces.length === 0) {
    return ["JSONRPC"]; // Default protocol
  }

  const protocols = new Set<string>();
  for (const iface of supportedInterfaces) {
    const binding = (iface.protocolBinding || "").toLowerCase();
    const protocol = PROTOCOL_BINDING_MAP[binding];
    if (protocol) {
      protocols.add(protocol);
    }
  }

  return protocols.size > 0 ? Array.from(protocols) : ["JSONRPC"];
}

// Agent Protocol Setting Popover Component
interface AgentProtocolSettingProps {
  agent: A2AExternalAgent;
  onProtocolChange: (agentId: string, protocolType: string) => void;
}

function AgentProtocolSetting({ agent, onProtocolChange }: Readonly<AgentProtocolSettingProps>) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const [selectedProtocol, setSelectedProtocol] = useState(
    (agent as any).protocol_type || "JSONRPC"
  );
  const [saving, setSaving] = useState(false);

  const availableProtocols = extractAvailableProtocols(agent.supported_interfaces);

  useEffect(() => {
    setSelectedProtocol((agent as any).protocol_type || "JSONRPC");
  }, [(agent as any).protocol_type]);

  const handleSave = () => {
    setSaving(true);
    onProtocolChange(String(agent.id), selectedProtocol);
    setSaving(false);
    setOpen(false);
  };

  return (
    <Popover
      content={
        <div style={{ minWidth: 200 }}>
          <div style={{ marginBottom: 12 }}>
            <Text type="secondary" className="text-xs">
              {t("a2a.protocol.selectProtocol")}
            </Text>
          </div>
          <Radio.Group
            value={selectedProtocol}
            onChange={(e) => setSelectedProtocol(e.target.value)}
            style={{ display: "flex", flexDirection: "column", gap: 8 }}
          >
            {PROTOCOL_TYPES.map((protocol) => {
              const isAvailable = availableProtocols.includes(protocol.value);
              return (
                <Radio
                  key={protocol.value}
                  value={protocol.value}
                  disabled={!isAvailable || protocol.disabled}
                  style={{ opacity: isAvailable ? 1 : 0.5 }}
                >
                  <Space>
                    <span>{protocol.label}</span>
                    {!isAvailable && (
                      <Tag color="default" style={{ marginLeft: 8 }}>
                        N/A
                      </Tag>
                    )}
                  </Space>
                </Radio>
              );
            })}
          </Radio.Group>
          <div style={{ marginTop: 12, textAlign: "right" }}>
            <Space>
              <Button size="small" onClick={() => setOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button
                type="primary"
                size="small"
                onClick={handleSave}
                loading={saving}
              >
                {t("common.save")}
              </Button>
            </Space>
          </div>
        </div>
      }
      title={t("a2a.protocol.settings")}
      trigger="click"
      open={open}
      onOpenChange={setOpen}
    >
      <Tooltip title={t("a2a.protocol.settings")}>
        <Button
          type="text"
          size="small"
          icon={<Settings size={14} />}
        />
      </Tooltip>
    </Popover>
  );
}

export default function A2AAgentDiscoveryModal({
  open,
  onClose,
  onAgentDiscovered,
  onDiscoverSuccess,
  nacosConfigId,
  localAgentId,
}: Readonly<A2AAgentDiscoveryModalProps>) {
  const { t } = useTranslation("common");
  const [messageApi, contextHolder] = message.useMessage();

  // Chat modal state
  const [chatModalOpen, setChatModalOpen] = useState(false);
  const [chatAgent, setChatAgent] = useState<A2AExternalAgent | null>(null);

  // Discovery mode
  const [mode, setMode] = useState<"url" | "nacos" | "list">("url");
  const [loading, setLoading] = useState(false);
  const [discoveredAgents, setDiscoveredAgents] = useState<A2AExternalAgent[]>([]);

  // URL mode state
  const [url, setUrl] = useState("");
  const [selectedAgent, setSelectedAgent] = useState<A2AExternalAgent | null>(null);

  // List mode state
  const [agents, setAgents] = useState<A2AExternalAgent[]>([]);
  const [loadingAgents, setLoadingAgents] = useState(false);
  const [refreshingId, setRefreshingId] = useState<string | null>(null);


  const loadAgents = async () => {
    setLoadingAgents(true);
    const result = await a2aClientService.listAgents();
    if (result.success && result.data) {
      setAgents(result.data);
    }
    setLoadingAgents(false);
  };

  // Discover from URL
  const handleDiscoverFromUrl = async () => {
    if (!url.trim()) {
      messageApi.error(t("a2a.discovery.urlRequired"));
      return;
    }

    try {
      new URL(url);
    } catch {
      messageApi.error(t("a2a.discovery.invalidUrl"));
      return;
    }

    setLoading(true);
    const result = await a2aClientService.discoverFromUrl({ url: url.trim() });
    setLoading(false);

    if (result.success && result.data) {
      setSelectedAgent(result.data);
      setDiscoveredAgents([result.data]);
      if (onDiscoverSuccess) {
        onDiscoverSuccess();
      }
      messageApi.success(t("a2a.discovery.success"));
    } else {
      messageApi.error(result.message || t("a2a.discovery.failed"));
    }
  };

  // Refresh agent card
  const handleRefresh = async (agentId: string) => {
    setRefreshingId(agentId);
    const result = await a2aClientService.refreshAgent(agentId);
    setRefreshingId(null);

    if (result.success) {
      messageApi.success(t("a2a.discovery.refreshSuccess"));
      loadAgents();
    } else {
      messageApi.error(result.message || t("a2a.discovery.refreshFailed"));
    }
  };

  // Delete agent
  const handleDelete = async (agentId: string) => {
    const result = await a2aClientService.deleteAgent(agentId);
    if (result.success) {
      messageApi.success(t("a2a.discovery.deleteSuccess"));
      loadAgents();
    } else {
      messageApi.error(result.message || t("a2a.discovery.deleteFailed"));
    }
  };

  // Update agent protocol
  const handleProtocolChange = async (agentId: string, protocolType: string) => {
    const result = await a2aClientService.updateAgentProtocol(agentId, protocolType);
    if (result.success) {
      messageApi.success(t("a2a.protocol.updateSuccess"));
      loadAgents();
    } else {
      messageApi.error(result.message || t("a2a.protocol.updateFailed"));
    }
  };

  // Add to local agent
  const handleAddToLocalAgent = async (agent: A2AExternalAgent) => {
    if (!localAgentId) {
      messageApi.error(t("a2a.discovery.noLocalAgent"));
      return;
    }

    const result = await a2aClientService.addRelation(
      localAgentId,
      agent.id
    );

    if (result.success) {
      messageApi.success(t("a2a.discovery.addRelationSuccess"));
      if (onAgentDiscovered) {
        onAgentDiscovered(agent);
      }
    } else {
      messageApi.error(result.message || t("a2a.discovery.addRelationFailed"));
    }
  };

  // Open chat modal
  const handleOpenChat = (agent: A2AExternalAgent) => {
    setChatAgent(agent);
    setChatModalOpen(true);
  };

  // Get status icon
  const getStatusIcon = (agent: A2AExternalAgent) => {
    if (!agent.is_available) {
      return (
        <Tooltip title={agent.last_check_result || t("a2a.status.unavailable")}>
          <XCircle className="text-red-500" size={16} />
        </Tooltip>
      );
    }
    if (agent.last_check_result === "OK") {
      return (
        <Tooltip title={t("a2a.status.available")}>
          <CheckCircle className="text-green-500" size={16} />
        </Tooltip>
      );
    }
    return (
      <Tooltip title={t("a2a.status.unknown")}>
        <AlertCircle className="text-yellow-500" size={16} />
      </Tooltip>
    );
  };

  // Agent columns for table
  const agentColumns = [
    {
      title: t("a2a.agent.name"),
      dataIndex: "name",
      key: "name",
      render: (name: string, record: A2AExternalAgent) => (
        <Space>
          {getStatusIcon(record)}
          <Text strong>{name}</Text>
        </Space>
      ),
    },
    {
      title: t("a2a.agent.description"),
      dataIndex: "description",
      key: "description",
      ellipsis: true,
      render: (desc: string) => (
        <Tooltip title={desc}>
          <Text type="secondary" className="max-w-xs truncate block">
            {desc || "-"}
          </Text>
        </Tooltip>
      ),
    },
    {
      title: t("a2a.agent.source"),
      dataIndex: "source_type",
      key: "source_type",
      width: 100,
      render: (type: string) => (
        <Tag color={type === "url" ? "blue" : "green"}>
          {type === "url" ? "URL" : "Nacos"}
        </Tag>
      ),
    },
    {
      title: t("common.actions"),
      key: "action",
      width: 280,
      render: (_: any, record: A2AExternalAgent) => (
        <Space size="small">
          <Tooltip title={t("a2a.discovery.refresh")}>
            <Button
              type="text"
              size="small"
              icon={
                <RefreshCw
                  size={14}
                  className={refreshingId === String(record.id) ? "animate-spin" : ""}
                />
              }
              onClick={() => handleRefresh(String(record.id))}
              loading={refreshingId === String(record.id)}
            />
          </Tooltip>
          <AgentProtocolSetting
            agent={record}
            onProtocolChange={handleProtocolChange}
          />
          <Tooltip title={t("a2a.chat.title")}>
            <Button
              type="text"
              size="small"
              icon={<MessageCircle size={14} />}
              onClick={() => handleOpenChat(record)}
            />
          </Tooltip>
          {localAgentId && (
            <Tooltip title={t("a2a.discovery.addAsSubAgent")}>
              <Button
                type="text"
                size="small"
                icon={<Plus size={14} />}
                onClick={() => handleAddToLocalAgent(record)}
              />
            </Tooltip>
          )}
          <Tooltip title={t("common.delete")}>
            <Button
              type="text"
              size="small"
              danger
              icon={<Trash2 size={14} />}
              onClick={() => handleDelete(String(record.id))}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

  return (
    <>
      {contextHolder}
      {chatAgent && (
        <A2AChatModal
          open={chatModalOpen}
          onClose={() => setChatModalOpen(false)}
          agent={chatAgent}
        />
      )}
      <Modal
        title={t("a2a.discovery.title")}
        open={open}
        onCancel={onClose}
        footer={null}
        width={1000}
        destroyOnHidden
      >
        <div style={{ padding: "0 0 16px 0" }}>
          <Tabs
            activeKey={mode}
            onChange={(key) => {
              setMode(key as "url" | "nacos" | "list");
              setDiscoveredAgents([]);
              setSelectedAgent(null);
              if (key === "list") {
                loadAgents();
              }
            }}
            items={[
              // URL Discovery Tab
              {
                key: "url",
                label: (
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                    <ExternalLink style={{ width: 16, height: 16 }} />
                    {t("a2a.discovery.tab.url")}
                  </span>
                ),
                children: (
                  <div className="space-y-4">
                    <Card size="small">
                      <Space direction="vertical" style={{ width: "100%" }} size="middle">
                        <Form layout="vertical">
                          <Form.Item
                            label={t("a2a.discovery.urlLabel")}
                            required
                            tooltip={t("a2a.discovery.urlTooltip")}
                          >
                            <div className="flex gap-2">
                              <Input
                                placeholder="https://example.com/.well-known/agent-xxx.json"
                                value={url}
                                onChange={(e) => setUrl(e.target.value)}
                                onPressEnter={handleDiscoverFromUrl}
                                className="flex-1"
                              />
                              <Button
                                type="primary"
                                onClick={handleDiscoverFromUrl}
                                loading={loading}
                                icon={<Search size={14} />}
                              >
                                {t("a2a.discovery.button")}
                              </Button>
                            </div>
                          </Form.Item>
                        </Form>
                      </Space>
                    </Card>

                    {loading && (
                      <div className="text-center py-8">
                        <Text type="secondary" className="block">
                          {t("a2a.discovery.discovering")}
                        </Text>
                      </div>
                    )}

                    {selectedAgent && !loading && (
                      <AgentDetailCard
                        agent={selectedAgent}
                        onAddToLocalAgent={
                          localAgentId ? () => handleAddToLocalAgent(selectedAgent) : undefined
                        }
                      />
                    )}
                  </div>
                ),
              },
              // Nacos Discovery Tab
              {
                key: "nacos",
                label: (
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                    <Globe style={{ width: 16, height: 16 }} />
                    {t("a2a.discovery.tab.nacos")}
                  </span>
                ),
                disabled: false,
                children: (
                  <NacosDiscoveryPanel
                    onAgentDiscovered={onAgentDiscovered}
                    onDiscoverSuccess={onDiscoverSuccess}
                    localAgentId={localAgentId}
                  />
                ),
              },
              // List Tab
              {
                key: "list",
                label: (
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                    <Eye style={{ width: 16, height: 16 }} />
                    {t("a2a.discovery.tab.list")}
                  </span>
                ),
                children: (
                  <div className="space-y-4">
                    <div className="flex justify-end">
                      <Button onClick={loadAgents} icon={<RefreshCw size={14} />}>
                        {t("common.refresh")}
                      </Button>
                    </div>

                    <Table
                      columns={agentColumns}
                      dataSource={agents}
                      rowKey="id"
                      loading={loadingAgents}
                      pagination={{ pageSize: 10 }}
                      size="small"
                      locale={{
                        emptyText: t("a2a.discovery.noAgents"),
                      }}
                    />
                  </div>
                ),
              },
            ]}
          />
        </div>
      </Modal>
    </>
  );
}

// Agent Detail Card Component
interface AgentDetailCardProps {
  agent: A2AExternalAgent;
  onAddToLocalAgent?: () => void;
}

function AgentDetailCard({ agent, onAddToLocalAgent }: Readonly<AgentDetailCardProps>) {
  const { t } = useTranslation("common");

  return (
    <div className="border rounded-lg p-4 bg-gray-50">
      <div className="flex justify-between items-start">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-2">
            <Globe size={18} className="text-blue-500" />
            <Text strong className="text-lg">{agent.name}</Text>
            <Tag color={agent.is_available ? "success" : "error"}>
              {agent.is_available
                ? t("a2a.status.available")
                : t("a2a.status.unavailable")}
            </Tag>
          </div>

          {agent.description && (
            <Text type="secondary" className="mb-3 block">
              {agent.description}
            </Text>
          )}

          <div className="space-y-1">
            {agent.supported_interfaces && agent.supported_interfaces.length > 0 && (
              <div className="mt-2">
                <Text type="secondary" className="text-xs">{t("a2a.agent.supportedInterfaces")}:</Text>
                <div className="mt-1 space-y-1 pl-4">
                  {agent.supported_interfaces.map((iface: any, idx: number) => (
                    <div key={idx} className="flex items-center gap-2 text-xs">
                      <Tag color="blue" className="text-xs px-1 py-0">{iface.protocolBinding}</Tag>
                      <span className="text-gray-500">{iface.url}</span>
                      <span className="text-gray-400 text-[10px]">v{iface.protocolVersion}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {onAddToLocalAgent && (
          <Button
            type="primary"
            icon={<Plus size={14} />}
            onClick={onAddToLocalAgent}
          >
            {t("a2a.discovery.addAsSubAgent")}
          </Button>
        )}
      </div>
    </div>
  );
}
