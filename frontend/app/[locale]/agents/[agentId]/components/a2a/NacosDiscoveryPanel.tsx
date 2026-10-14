"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  Input,
  Form,
  Table,
  Tag,
  Space,
  Typography,
  Card,
  Tooltip,
  message,
  Select,
} from "antd";
import {
  RefreshCw,
  Trash2,
  Plus,
  Search,
  Wifi,
  Edit,
} from "lucide-react";
import { a2aClientService, A2AExternalAgent, NacosConfig } from "@/services/a2aService";
import log from "@/lib/logger";

const { Text, Title } = Typography;

interface NacosDiscoveryPanelProps {
  onAgentDiscovered?: (agent: A2AExternalAgent) => void;
  onDiscoverSuccess?: () => void;
  localAgentId?: number;
}

interface NewNacosConfigForm {
  name: string;
  nacos_addr: string;
  username: string;
  password: string;
  namespace_id: string;
}

export default function NacosDiscoveryPanel({
  onAgentDiscovered,
  onDiscoverSuccess,
  localAgentId,
}: NacosDiscoveryPanelProps) {
  const { t } = useTranslation("common");
  const [messageApi, contextHolder] = message.useMessage();

  // Add/Edit config form state
  const [showAddNacosForm, setShowAddNacosForm] = useState(false);
  const [editingConfigId, setEditingConfigId] = useState<string | null>(null);
  const [nacosConfig, setNacosConfig] = useState<NewNacosConfigForm>({
    name: "",
    nacos_addr: "",
    username: "",
    password: "",
    namespace_id: "public",
  });
  const [savingNacosConfig, setSavingNacosConfig] = useState(false);
  const [testingConnection, setTestingConnection] = useState(false);

  // Existing configs list state
  const [nacosConfigs, setNacosConfigs] = useState<NacosConfig[]>([]);
  const [loadingNacosConfigs, setLoadingNacosConfigs] = useState(false);
  const [selectedNacosConfigId, setSelectedNacosConfigId] = useState<string | null>(null);
  const [testingConfigId, setTestingConfigId] = useState<string | null>(null);

  // Scan state
  const [agentNames, setAgentNames] = useState<string[]>([]);
  const [scanning, setScanning] = useState(false);
  const [discoveredAgents, setDiscoveredAgents] = useState<A2AExternalAgent[]>([]);

  // Load configs on mount
  useEffect(() => {
    loadNacosConfigs();
  }, []);

  const loadNacosConfigs = async () => {
    setLoadingNacosConfigs(true);
    const result = await a2aClientService.listNacosConfigs();
    if (result.success && result.data) {
      setNacosConfigs(result.data);
    }
    setLoadingNacosConfigs(false);
  };

  const handleTestNacosConnection = async (configToTest?: NacosConfig) => {
    const addr = configToTest?.nacos_addr ?? nacosConfig.nacos_addr;
    if (!addr.trim()) {
      messageApi.error(t("a2a.discovery.nacosAddrRequired"));
      return;
    }

    const isTestingExisting = !!configToTest;
    if (isTestingExisting) {
      setTestingConfigId(configToTest!.config_id);
    } else {
      setTestingConnection(true);
    }
    try {
      const result = await a2aClientService.testNacosConnection({
        nacos_addr: addr.trim(),
        namespace_id: configToTest?.namespace_id || nacosConfig.namespace_id || "public",
        nacos_username: configToTest?.nacos_username ?? (nacosConfig.username.trim() || undefined),
        nacos_password: configToTest?.nacos_password ?? (nacosConfig.password.trim() || undefined),
      });

      if (result.success) {
        messageApi.success(result.message || t("a2a.discovery.testConnectionSuccess"));
      } else {
        messageApi.error(result.message || t("a2a.discovery.testConnectionFailed"));
      }
    } catch (error) {
      log.error("Failed to test Nacos connection:", error);
      messageApi.error(t("a2a.discovery.testConnectionFailed"));
    }
    if (isTestingExisting) {
      setTestingConfigId(null);
    } else {
      setTestingConnection(false);
    }
  };

  const handleAddNacosConfig = async () => {
    if (!nacosConfig.name.trim()) {
      messageApi.error(t("a2a.discovery.nacosNameRequired"));
      return;
    }
    if (!nacosConfig.nacos_addr.trim()) {
      messageApi.error(t("a2a.discovery.nacosAddrRequired"));
      return;
    }

    setSavingNacosConfig(true);
    try {
      const result = await a2aClientService.createNacosConfig({
        name: nacosConfig.name.trim(),
        nacos_addr: nacosConfig.nacos_addr.trim(),
        namespace_id: nacosConfig.namespace_id || "public",
        nacos_username: nacosConfig.username.trim() || undefined,
        nacos_password: nacosConfig.password.trim() || undefined,
      });

      if (result.success && result.data) {
        messageApi.success(t("a2a.discovery.addNacosConfigSuccess"));
        await loadNacosConfigs();
        setSelectedNacosConfigId(result.data.config_id);
        setNacosConfig({ name: "", nacos_addr: "", username: "", password: "", namespace_id: "public" });
        setShowAddNacosForm(false);
      } else {
        messageApi.error(result.message || t("a2a.discovery.addNacosConfigFailed"));
      }
    } catch (error) {
      log.error("Failed to add Nacos config:", error);
      messageApi.error(t("a2a.discovery.addNacosConfigFailed"));
    }
    setSavingNacosConfig(false);
  };

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

  const handleEditNacosConfig = (config: NacosConfig) => {
    setEditingConfigId(config.config_id);
    setNacosConfig({
      name: config.name,
      nacos_addr: config.nacos_addr,
      username: config.nacos_username || "",
      password: config.nacos_password || "",
      namespace_id: config.namespace_id || "public",
    });
    setShowAddNacosForm(true);
  };

  const handleUpdateNacosConfig = async () => {
    if (!editingConfigId) return;

    if (!nacosConfig.name.trim()) {
      messageApi.error(t("a2a.discovery.nacosNameRequired"));
      return;
    }
    if (!nacosConfig.nacos_addr.trim()) {
      messageApi.error(t("a2a.discovery.nacosAddrRequired"));
      return;
    }

    setSavingNacosConfig(true);
    try {
      const result = await a2aClientService.updateNacosConfig(editingConfigId, {
        name: nacosConfig.name.trim(),
        nacos_addr: nacosConfig.nacos_addr.trim(),
        namespace_id: nacosConfig.namespace_id || "public",
        nacos_username: nacosConfig.username.trim() || undefined,
        nacos_password: nacosConfig.password.trim() || undefined,
      });

      if (result.success) {
        messageApi.success(t("a2a.discovery.updateNacosConfigSuccess"));
        setShowAddNacosForm(false);
        handleCancelEdit();
        await loadNacosConfigs();
      } else {
        messageApi.error(result.message || t("a2a.discovery.updateNacosConfigFailed"));
      }
    } catch (error) {
      log.error("Failed to update Nacos config:", error);
      messageApi.error(t("a2a.discovery.updateNacosConfigFailed"));
    }
    setSavingNacosConfig(false);
  };

  const handleCancelEdit = () => {
    setEditingConfigId(null);
    setNacosConfig({
      name: "",
      nacos_addr: "",
      username: "",
      password: "",
      namespace_id: "public",
    });
  };

  const handleDiscoverFromNacos = async () => {
    if (!selectedNacosConfigId) {
      messageApi.error(t("a2a.discovery.selectNacosConfig"));
      return;
    }

    if (agentNames.length === 0) {
      messageApi.error(t("a2a.discovery.enterAgentNames"));
      return;
    }

    const selectedConfig = nacosConfigs.find(c => c.config_id === selectedNacosConfigId);
    setScanning(true);
    const result = await a2aClientService.discoverFromNacos({
      nacos_config_id: selectedNacosConfigId,
      agent_names: agentNames.map(name => name.trim()).filter(name => name.length > 0),
      namespace: selectedConfig?.namespace_id || "public",
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
        result.data.forEach((agent) => {
          if (onAgentDiscovered) {
            onAgentDiscovered(agent);
          }
        });
        if (onDiscoverSuccess) {
          onDiscoverSuccess();
        }
      }
    } else {
      messageApi.error(result.message || t("a2a.discovery.scanFailed"));
    }
  };

  const handleAddToLocalAgent = async (agent: A2AExternalAgent) => {
    if (!localAgentId) return;

    const result = await a2aClientService.addRelation(localAgentId, agent.id);
    if (result.success) {
      messageApi.success(t("a2a.discovery.addToLocalAgentSuccess"));
    } else {
      messageApi.error(result.message || t("a2a.discovery.addToLocalAgentFailed"));
    }
  };

  // Nacos config table columns
  const nacosConfigColumns = [
    {
      title: t("a2a.discovery.nacosName"),
      dataIndex: "name",
      key: "name",
      width: "20%",
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
      width: "20%",
      render: (text: string) => <Tag>{text}</Tag>,
    },
    {
      title: t("common.actions"),
      key: "action",
      width: "15%",
      render: (_: any, record: NacosConfig) => (
        <Space size="small">
          <Tooltip title={t("a2a.discovery.editNacosConfig")}>
            <Button
              type="link"
              size="small"
              icon={<Edit size={14} />}
              onClick={() => handleEditNacosConfig(record)}
            />
          </Tooltip>
          <Tooltip title={t("a2a.discovery.testConnection")}>
            <Button
              type="link"
              size="small"
              icon={<Wifi size={14} />}
              loading={testingConfigId === record.config_id}
              onClick={() => handleTestNacosConnection(record)}
            />
          </Tooltip>
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

  return (
    <>
      {contextHolder}
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
                onClick={() => {
                  setEditingConfigId(null);
                  setNacosConfig({
                    name: "",
                    nacos_addr: "",
                    username: "",
                    password: "",
                    namespace_id: "public",
                  });
                  setShowAddNacosForm(true);
                }}
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

          {/* Add/Edit Nacos Config Form - Toggleable */}
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
                    value={nacosConfig.name}
                    onChange={(e) =>
                      setNacosConfig({ ...nacosConfig, name: e.target.value })
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
                    value={nacosConfig.nacos_addr}
                    onChange={(e) =>
                      setNacosConfig({ ...nacosConfig, nacos_addr: e.target.value })
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
                    value={nacosConfig.namespace_id}
                    onChange={(e) =>
                      setNacosConfig({ ...nacosConfig, namespace_id: e.target.value })
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
                    value={nacosConfig.username}
                    onChange={(e) =>
                      setNacosConfig({ ...nacosConfig, username: e.target.value })
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
                    value={nacosConfig.password}
                    onChange={(e) =>
                      setNacosConfig({ ...nacosConfig, password: e.target.value })
                    }
                    disabled={savingNacosConfig}
                  />
                </Form.Item>

                <div className="flex justify-end gap-2">
                  <Button
                    onClick={() => {
                      setShowAddNacosForm(false);
                      handleCancelEdit();
                    }}
                    disabled={savingNacosConfig}
                  >
                    {t("common.cancel")}
                  </Button>
                  <Button
                    onClick={() => handleTestNacosConnection()}
                    loading={testingConnection}
                    icon={<Wifi size={14} />}
                  >
                    {t("a2a.discovery.testConnection")}
                  </Button>
                  <Button
                    type="primary"
                    onClick={editingConfigId ? handleUpdateNacosConfig : handleAddNacosConfig}
                    loading={savingNacosConfig}
                    icon={editingConfigId ? <Edit size={14} /> : <Plus size={14} />}
                  >
                    {editingConfigId ? t("common.save") : t("a2a.discovery.saveAndSelect")}
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
    </>
  );
}

// Agent Detail Card Component
interface AgentDetailCardProps {
  agent: A2AExternalAgent;
  onAddToLocalAgent?: () => void;
}

function AgentDetailCard({ agent, onAddToLocalAgent }: AgentDetailCardProps) {
  const { t } = useTranslation("common");

  return (
    <Card size="small">
      <div className="flex justify-between items-start">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <Text strong>{agent.name}</Text>
            <Tag color={agent.source_type === "url" ? "blue" : "green"}>
              {agent.source_type === "url" ? "URL" : "Nacos"}
            </Tag>
          </div>
          <Text type="secondary" className="block text-sm">
            {agent.description || t("a2a.discovery.noDescription")}
          </Text>
          <Text type="secondary" className="block text-xs mt-1">
            {agent.agent_url || agent.source_url}
          </Text>
        </div>
        {onAddToLocalAgent && (
          <Button
            type="primary"
            size="small"
            icon={<Plus size={14} />}
            onClick={onAddToLocalAgent}
          >
            {t("a2a.discovery.addToLocalAgent")}
          </Button>
        )}
      </div>
    </Card>
  );
}
