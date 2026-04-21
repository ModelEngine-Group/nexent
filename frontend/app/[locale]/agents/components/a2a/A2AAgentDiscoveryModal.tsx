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
import { a2aClientService, A2AExternalAgent, NacosConfig } from "@/services/a2aService";
import A2AChatModal from "./A2AChatModal";
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
  const [mode, setMode] = useState<"url" | "nacos">("url");
  const [loading, setLoading] = useState(false);
  const [discoveredAgents, setDiscoveredAgents] = useState<A2AExternalAgent[]>([]);

  // URL mode state
  const [url, setUrl] = useState("");
  const [selectedAgent, setSelectedAgent] = useState<A2AExternalAgent | null>(null);

  // Nacos mode state - Add new config form (toggleable)
  const [showAddNacosForm, setShowAddNacosForm] = useState(false);
  const [newNacosConfig, setNewNacosConfig] = useState({
    name: "",
    nacos_addr: "",
    username: "",
    password: "",
    namespace_id: "public",
  });
  const [savingNacosConfig, setSavingNacosConfig] = useState(false);

  // Nacos mode state - Existing configs list
  const [nacosConfigs, setNacosConfigs] = useState<NacosConfig[]>([]);
  const [loadingNacosConfigs, setLoadingNacosConfigs] = useState(false);
  const [selectedNacosConfigId, setSelectedNacosConfigId] = useState<string | null>(null);

  // Nacos scan state
  const [agentNames, setAgentNames] = useState<string[]>([]);
  const [scanning, setScanning] = useState(false);

  // List mode state
  const [agents, setAgents] = useState<A2AExternalAgent[]>([]);
  const [loadingAgents, setLoadingAgents] = useState(false);
  const [refreshingId, setRefreshingId] = useState<string | null>(null);

  // Load Nacos configs and existing agents on mount
  useEffect(() => {
    if (open) {
      loadNacosConfigs();
      loadAgents();
    }
  }, [open]);

  const loadNacosConfigs = async () => {
    setLoadingNacosConfigs(true);
    const result = await a2aClientService.listNacosConfigs();
    if (result.success && result.data) {
      setNacosConfigs(result.data);
    }
    setLoadingNacosConfigs(false);
  };

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
      loadAgents();
      if (onDiscoverSuccess) {
        onDiscoverSuccess();
      }
      messageApi.success(t("a2a.discovery.success"));
    } else {
      messageApi.error(result.message || t("a2a.discovery.failed"));
    }
  };

  // Add new Nacos config
  const handleAddNacosConfig = async () => {
    if (!newNacosConfig.name.trim()) {
      messageApi.error(t("a2a.discovery.nacosNameRequired"));
      return;
    }
    if (!newNacosConfig.nacos_addr.trim()) {
      messageApi.error(t("a2a.discovery.nacosAddrRequired"));
      return;
    }

    setSavingNacosConfig(true);
    try {
      const result = await a2aClientService.createNacosConfig({
        name: newNacosConfig.name.trim(),
        nacos_addr: newNacosConfig.nacos_addr.trim(),
        namespace_id: newNacosConfig.namespace_id || "public",
        nacos_username: newNacosConfig.username.trim() || undefined,
        nacos_password: newNacosConfig.password.trim() || undefined,
      });

      if (result.success && result.data) {
        messageApi.success(t("a2a.discovery.addNacosConfigSuccess"));
        await loadNacosConfigs();
        setSelectedNacosConfigId(result.data.config_id);
        setNewNacosConfig({ name: "", nacos_addr: "", username: "", password: "", namespace_id: "public" });
      } else {
        messageApi.error(result.message || t("a2a.discovery.addNacosConfigFailed"));
      }
    } catch (error) {
      log.error("Failed to add Nacos config:", error);
      messageApi.error(t("a2a.discovery.addNacosConfigFailed"));
    }
    setSavingNacosConfig(false);
  };

  // Delete Nacos config
  const handleDeleteNacosConfig = async (configId: string) => {
    const result = await a2aClientService.deleteNacosConfig(configId);
    if (result.success) {
      messageApi.success(t("a2a.discovery.deleteNacosConfigSuccess"));
      if (selectedNacosConfigId === configId) {
        setSelectedNacosConfigId(null);
      }
      await loadNacosConfigs();
    } else {
      messageApi.error(result.message || t("a2a.discovery.deleteNacosConfigFailed"));
    }
  };

  // Discover from Nacos
  const handleDiscoverFromNacos = async () => {
    if (!selectedNacosConfigId) {
      messageApi.error(t("a2a.discovery.selectNacosConfig"));
      return;
    }

    if (agentNames.length === 0) {
      messageApi.error(t("a2a.discovery.enterAgentNames"));
      return;
    }

    setScanning(true);
    const result = await a2aClientService.discoverFromNacos({
      nacos_config_id: selectedNacosConfigId,
      agent_names: agentNames,
      namespace: newNacosConfig.namespace_id || "public",
    });
    setScanning(false);

    if (result.success && result.data) {
      setDiscoveredAgents(result.data);
      if (result.data.length === 0) {
        messageApi.warning(t("a2a.discovery.noAgentsFound"));
      } else {
        messageApi.success(
          t("a2a.discovery.foundAgents", { count: result.data.length })
        );
      }
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

  // Nacos config table columns
  const nacosConfigColumns = [
    {
      title: t("a2a.discovery.nacosName"),
      dataIndex: "name",
      key: "name",
      width: "30%",
      ellipsis: true,
      render: (text: string) => <Text strong>{text}</Text>,
    },
    {
      title: t("a2a.discovery.nacosAddr"),
      dataIndex: "nacos_addr",
      key: "nacos_addr",
      width: "40%",
      ellipsis: true,
      render: (text: string) => <Text type="secondary">{text}</Text>,
    },
    {
      title: t("a2a.discovery.namespace"),
      dataIndex: "namespace_id",
      key: "namespace_id",
      width: "15%",
      render: (text: string) => <Tag>{text}</Tag>,
    },
    {
      title: t("common.actions"),
      key: "action",
      width: "15%",
      render: (_: any, record: NacosConfig) => (
        <Space size="small">
          <Tooltip title={t("a2a.discovery.scan")}>
            <Button
              type="link"
              size="small"
              icon={<Search size={14} />}
              onClick={() => setSelectedNacosConfigId(record.config_id)}
            />
          </Tooltip>
          <Tooltip title={t("common.delete")}>
            <Button
              type="link"
              size="small"
              danger
              icon={<Trash2 size={14} />}
              onClick={() => handleDeleteNacosConfig(record.config_id)}
            />
          </Tooltip>
        </Space>
      ),
    },
  ];

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
              setMode(key as "url" | "nacos");
              setDiscoveredAgents([]);
              setSelectedAgent(null);
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
              // Nacos Discovery Tab (disabled - feature pending)
              {
                key: "nacos",
                label: (
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                    <Globe style={{ width: 16, height: 16 }} />
                    {t("a2a.discovery.tab.nacos")}
                    <Tag color="default" style={{ marginLeft: 4, fontSize: 10 }}>Coming Soon</Tag>
                  </span>
                ),
                disabled: true,
                children: (
                  <div className="space-y-4">
                    {/* Existing Nacos Configs List */}
                    <div>
                      <div className="flex justify-between items-center mb-2">
                        <Title level={5} style={{ margin: 0 }}>
                          {t("a2a.discovery.nacosConfigList")}
                        </Title>
                        <Space>
                          <Button
                            type="primary"
                            icon={<Plus size={14} />}
                            onClick={() => setShowAddNacosForm(!showAddNacosForm)}
                          >
                            {t("a2a.discovery.addNacosConfig")}
                          </Button>
                          <Button
                            size="small"
                            icon={<RefreshCw size={14} />}
                            onClick={loadNacosConfigs}
                            loading={loadingNacosConfigs}
                          >
                            {t("common.refresh")}
                          </Button>
                        </Space>
                      </div>

                      {/* Add Nacos Config Form - Toggleable */}
                      {showAddNacosForm && (
                        <Card size="small" className="mb-4">
                          <Form 
                            layout="horizontal" 
                            labelAlign="left"
                            labelCol={{ span: 5 }}
                            wrapperCol={{ span: 19 }}
                          >
                            <Form.Item
                              label={t("a2a.discovery.nacosName")}
                              required
                            >
                              <Input
                                placeholder={t("a2a.discovery.nacosNamePlaceholder")}
                                value={newNacosConfig.name}
                                onChange={(e) =>
                                  setNewNacosConfig({ ...newNacosConfig, name: e.target.value })
                                }
                                disabled={savingNacosConfig}
                              />
                            </Form.Item>

                            <Form.Item
                              label={t("a2a.discovery.nacosAddr")}
                              required
                              tooltip={t("a2a.discovery.nacosAddrTooltip")}
                            >
                              <Input
                                placeholder="http://nacos-server:8848"
                                value={newNacosConfig.nacos_addr}
                                onChange={(e) =>
                                  setNewNacosConfig({ ...newNacosConfig, nacos_addr: e.target.value })
                                }
                                disabled={savingNacosConfig}
                              />
                            </Form.Item>

                            <Form.Item
                              label={t("a2a.discovery.namespace")}
                              tooltip={t("a2a.discovery.namespaceTooltip")}
                            >
                              <Input
                                placeholder="public"
                                value={newNacosConfig.namespace_id}
                                onChange={(e) =>
                                  setNewNacosConfig({ ...newNacosConfig, namespace_id: e.target.value })
                                }
                                disabled={savingNacosConfig}
                              />
                            </Form.Item>

                            <Form.Item
                              label={t("a2a.discovery.nacosUsername")}
                              tooltip={t("a2a.discovery.nacosUsernameTooltip")}
                            >
                              <Input
                                placeholder={t("a2a.discovery.nacosUsernamePlaceholder")}
                                value={newNacosConfig.username}
                                onChange={(e) =>
                                  setNewNacosConfig({ ...newNacosConfig, username: e.target.value })
                                }
                                disabled={savingNacosConfig}
                              />
                            </Form.Item>

                            <Form.Item
                              label={t("a2a.discovery.nacosPassword")}
                              tooltip={t("a2a.discovery.nacosPasswordTooltip")}
                            >
                              <Input.Password
                                placeholder={t("a2a.discovery.nacosPasswordPlaceholder")}
                                value={newNacosConfig.password}
                                onChange={(e) =>
                                  setNewNacosConfig({ ...newNacosConfig, password: e.target.value })
                                }
                                disabled={savingNacosConfig}
                              />
                            </Form.Item>

                            <div className="flex justify-end gap-2">
                              <Button onClick={() => setShowAddNacosForm(false)}>
                                {t("common.cancel")}
                              </Button>
                              <Button
                                type="primary"
                                onClick={handleAddNacosConfig}
                                loading={savingNacosConfig}
                                icon={<Plus size={14} />}
                              >
                                {t("a2a.discovery.saveAndSelect")}
                              </Button>
                            </div>
                          </Form>
                        </Card>
                      )}

                      <Table
                        columns={nacosConfigColumns}
                        dataSource={nacosConfigs}
                        rowKey="config_id"
                        loading={loadingNacosConfigs}
                        size="small"
                        pagination={false}
                        scroll={{ y: 200 }}
                        locale={{ emptyText: t("a2a.discovery.noNacosConfigs") }}
                        rowClassName={(record) =>
                          record.config_id === selectedNacosConfigId ? "bg-blue-50" : ""
                        }
                        onRow={(record) => ({
                          onClick: () => setSelectedNacosConfigId(record.config_id),
                          style: { cursor: "pointer" },
                        })}
                      />
                    </div>

                    {/* Scan Section - Only show when config is selected */}
                    {selectedNacosConfigId && (
                      <Card size="small" title={t("a2a.discovery.scanAgents")}>
                        <Form layout="vertical">
                          <Form.Item
                            label={t("a2a.discovery.agentNames")}
                            required
                            tooltip={t("a2a.discovery.agentNamesTooltip")}
                          >
                            <Select
                              mode="tags"
                              placeholder={t("a2a.discovery.enterAgentNames")}
                              value={agentNames}
                              onChange={setAgentNames}
                              className="w-full"
                              tokenSeparators={[","]}
                            />
                          </Form.Item>
                          <Button
                            type="primary"
                            onClick={handleDiscoverFromNacos}
                            loading={scanning}
                            icon={<Search size={14} />}
                          >
                            {t("a2a.discovery.scan")}
                          </Button>
                        </Form>
                      </Card>
                    )}

                    {/* Discovered Agents */}
                    {discoveredAgents.length > 0 && (
                      <div className="space-y-4">
                        <Text strong>
                          {t("a2a.discovery.discoveredAgents", {
                            count: discoveredAgents.length,
                          })}
                        </Text>
                        {discoveredAgents.map((agent) => (
                          <AgentDetailCard
                            key={String(agent.id)}
                            agent={agent}
                            onAddToLocalAgent={
                              localAgentId
                                ? () => handleAddToLocalAgent(agent)
                                : undefined
                            }
                          />
                        ))}
                      </div>
                    )}
                  </div>
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
