"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import {
  Modal,
  Button,
  Input,
  Table,
  Space,
  Typography,
  Card,
  Divider,
  Tooltip,
  App,
} from "antd";
import {
  Trash,
  Eye,
  Plus,
  LoaderCircle,
  Maximize,
  Minimize,
  RefreshCw,
  FileText,
  Container,
} from "lucide-react";

import { McpConfigModalProps, AgentRefreshEvent } from "@/types/agentConfig";
import {
  getMcpServerList,
  addMcpServer,
  deleteMcpServer,
  getMcpTools,
  updateToolList,
  checkMcpServerHealth,
  addMcpFromConfig,
  getMcpContainers,
  getMcpContainerLogs,
  deleteMcpContainer,
} from "@/services/mcpService";
import { McpServer, McpTool, McpContainer } from "@/types/agentConfig";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import log from "@/lib/logger";

const { Text, Title } = Typography;

export default function McpConfigModal({
  visible,
  onCancel,
}: McpConfigModalProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { confirm } = useConfirmModal();
  const [serverList, setServerList] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(false);
  const [addingServer, setAddingServer] = useState(false);
  const [newServerName, setNewServerName] = useState("");
  const [newServerUrl, setNewServerUrl] = useState("");
  const [toolsModalVisible, setToolsModalVisible] = useState(false);
  const [currentServerTools, setCurrentServerTools] = useState<McpTool[]>([]);
  const [currentServerName, setCurrentServerName] = useState("");
  const [loadingTools, setLoadingTools] = useState(false);
  const [expandedDescriptions, setExpandedDescriptions] = useState<Set<string>>(
    new Set()
  );
  const [updatingTools, setUpdatingTools] = useState(false);
  const [healthCheckLoading, setHealthCheckLoading] = useState<{
    [key: string]: boolean;
  }>({});

  // Container-related state
  const [containerList, setContainerList] = useState<McpContainer[]>([]);
  const [loadingContainers, setLoadingContainers] = useState(false);
  const [addingContainer, setAddingContainer] = useState(false);
  const [containerConfigJson, setContainerConfigJson] = useState("");
  const [containerPort, setContainerPort] = useState<number | undefined>(undefined);
  const [logsModalVisible, setLogsModalVisible] = useState(false);
  const [currentContainerLogs, setCurrentContainerLogs] = useState("");
  const [currentContainerId, setCurrentContainerId] = useState("");
  const [loadingLogs, setLoadingLogs] = useState(false);
  const delayedContainerRefreshRef = useRef<number | undefined>(undefined);

  const actionsLocked = updatingTools || addingContainer;

  // Helper function to refresh tools and agents asynchronously
  const refreshToolsAndAgents = async () => {
    setUpdatingTools(true);
    try {
      // Update tool list to refresh MCP tool availability status
      const updateResult = await updateToolList();
      if (updateResult.success) {
        // Notify parent component to update tool list
        window.dispatchEvent(new CustomEvent("toolsUpdated"));
      }

      // Refresh agent list to update agent availability status
      window.dispatchEvent(
        new CustomEvent("refreshAgentList") as AgentRefreshEvent
      );
    } catch (error) {
      // Silently handle errors to avoid interrupting user experience
      log.error("Failed to refresh tools and agents:", error);
    } finally {
      setUpdatingTools(false);
    }
  };

  // Load MCP server list
  const loadServerList = async () => {
    setLoading(true);
    try {
      const result = await getMcpServerList();
      if (result.success) {
        setServerList(result.data);
      } else {
        message.error(result.message);
      }
    } catch (error) {
      message.error(t("mcpConfig.message.loadServerListFailed"));
    } finally {
      setLoading(false);
    }
  };

  // Add MCP server
  const handleAddServer = async () => {
    if (!newServerName.trim() || !newServerUrl.trim()) {
      message.error(t("mcpConfig.message.completeServerInfo"));
      return;
    }

    // Validate server name format
    const serverName = newServerName.trim();
    const nameRegex = /^[a-zA-Z0-9]+$/;

    if (!nameRegex.test(serverName)) {
      message.error(t("mcpConfig.message.invalidServerName"));
      return;
    }

    if (serverName.length > 20) {
      message.error(t("mcpConfig.message.serverNameTooLong"));
      return;
    }

    // Check if server with same name already exists
    const exists = serverList.some(
      (server) =>
        server.service_name === serverName ||
        server.mcp_url === newServerUrl.trim()
    );
    if (exists) {
      message.error(t("mcpConfig.message.serverExists"));
      return;
    }

    setAddingServer(true);
    try {
      const result = await addMcpServer(newServerUrl.trim(), serverName);
      if (result.success) {
        setNewServerName("");
        setNewServerUrl("");
        await loadServerList(); // Reload list

        // Refresh tools and agents asynchronously after adding server
        // This will update MCP tool availability and agent availability status
        await refreshToolsAndAgents();

        // Show success message after refresh completes to avoid message overlap
        message.success(t("mcpService.message.addServerSuccess"));
      } else {
        message.error(result.message);
      }
    } catch (error) {
      message.error(t("mcpConfig.message.addServerFailed"));
    } finally {
      setAddingServer(false);
    }
  };

  // Delete MCP server
  const handleDeleteServer = async (server: McpServer) => {
    confirm({
      title: t("mcpConfig.delete.confirmTitle"),
      content: t("mcpConfig.delete.confirmContent", {
        name: server.service_name,
      }),
      okText: t("common.delete", "Delete"),
      onOk: async () => {
        try {
          const result = await deleteMcpServer(
            server.mcp_url,
            server.service_name
          );
          if (result.success) {
            await loadServerList(); // Reload list

            // Show success message immediately
            message.success(t("mcpService.message.deleteServerSuccess"));

            // This will update MCP tool availability and agent availability status
            refreshToolsAndAgents().catch((error) => {
              log.error("Failed to refresh tools and agents after deletion:", error);
            });
          } else {
            message.error(result.message);
            // Throw error to prevent modal from closing
            throw new Error(result.message);
          }
        } catch (error) {
          message.error(t("mcpConfig.message.deleteServerFailed"));
          // Throw error to prevent modal from closing
          throw error;
        }
      },
    });
  };

  // View server tools
  const handleViewTools = async (server: McpServer) => {
    setCurrentServerName(server.service_name);
    setLoadingTools(true);
    setToolsModalVisible(true);
    setExpandedDescriptions(new Set()); // Reset expand state

    try {
      const result = await getMcpTools(server.service_name, server.mcp_url);
      if (result.success) {
        setCurrentServerTools(result.data);
      } else {
        message.error(result.message);
        setCurrentServerTools([]);
      }
    } catch (error) {
      message.error(t("mcpConfig.message.getToolsFailed"));
      setCurrentServerTools([]);
    } finally {
      setLoadingTools(false);
    }
  };

  // Toggle description expand state
  const toggleDescription = (toolName: string) => {
    const newExpanded = new Set(expandedDescriptions);
    if (newExpanded.has(toolName)) {
      newExpanded.delete(toolName);
    } else {
      newExpanded.add(toolName);
    }
    setExpandedDescriptions(newExpanded);
  };

  // Validate server connectivity
  const handleCheckHealth = async (server: McpServer) => {
    const key = `${server.service_name}__${server.mcp_url}`;
    message.info(
      t("mcpConfig.message.healthChecking", { name: server.service_name })
    );
    setHealthCheckLoading((prev) => ({ ...prev, [key]: true }));
    try {
      const result = await checkMcpServerHealth(
        server.mcp_url,
        server.service_name
      );
      if (result.success) {
        message.success(t("mcpConfig.message.healthCheckSuccess"));
        await loadServerList();

        // Refresh tools and agents asynchronously after health check
        // This will update MCP tool availability and agent availability status
        refreshToolsAndAgents();
      } else {
        message.error(
          result.message || t("mcpConfig.message.healthCheckFailed")
        );
        await loadServerList();

        // Refresh tools and agents even if health check failed
        // This will update MCP tool availability and agent availability status
        refreshToolsAndAgents();
      }
    } catch (error) {
      message.error(t("mcpConfig.message.healthCheckFailed"));
      await loadServerList();

      // Refresh tools and agents even if health check failed
      // This will update MCP tool availability and agent availability status
      refreshToolsAndAgents();
    } finally {
      setHealthCheckLoading((prev) => ({ ...prev, [key]: false }));
    }
  };

  // Server list table column definitions
  const columns = [
    {
      title: t("mcpConfig.serverList.column.name"),
      dataIndex: "service_name",
      key: "service_name",
      width: "25%",
      ellipsis: true,
      render: (text: string, record: McpServer) => {
        const key = `${record.service_name}__${record.mcp_url}`;
        return (
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div
              style={{
                width: 16,
                height: 16,
                borderRadius: "50%",
                backgroundColor: record.status ? "#52c41a" : "#ff4d4f",
                flexShrink: 0,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                border: "1px solid #d9d9d9",
                boxShadow: "0 0 2px #ccc",
              }}
            >
              {healthCheckLoading[key] ? (
                <LoaderCircle
                  className="animate-spin"
                  style={{ color: record.status ? "#52c41a" : "#ff4d4f", width: 16, height: 16 }}
                />
              ) : null}
            </div>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
              {text}
            </span>
          </div>
        );
      },
    },
    {
      title: t("mcpConfig.serverList.column.url"),
      dataIndex: "mcp_url",
      key: "mcp_url",
      width: "40%",
      ellipsis: true,
    },
    {
      title: t("mcpConfig.serverList.column.action"),
      key: "action",
      width: "35%",
      render: (_: any, record: McpServer) => {
        const key = `${record.service_name}__${record.mcp_url}`;
        return (
          <Space size="small">
            <Button
              type="link"
              icon={<RefreshCw size={16} className={healthCheckLoading[key] ? "animate-spin" : ""} />}
              onClick={() => handleCheckHealth(record)}
              size="small"
              loading={healthCheckLoading[key]}
                disabled={actionsLocked}
            >
              {t("mcpConfig.serverList.button.healthCheck")}
            </Button>
            {record.status ? (
              <Button
                type="link"
                icon={<Eye size={16} />}
                onClick={() => handleViewTools(record)}
                size="small"
                  disabled={actionsLocked}
              >
                {t("mcpConfig.serverList.button.viewTools")}
              </Button>
            ) : (
              <Tooltip
                title={t("mcpConfig.serverList.button.viewToolsDisabledHint")}
                placement="top"
              >
                <Button
                  type="link"
                  icon={<Eye size={16} />}
                  size="small"
                  disabled
                >
                  {t("mcpConfig.serverList.button.viewTools")}
                </Button>
              </Tooltip>
            )}
            <Button
              type="link"
              danger
              icon={<Trash size={16} />}
              onClick={() => handleDeleteServer(record)}
              size="small"
                  disabled={actionsLocked}
            >
              {t("mcpConfig.serverList.button.delete")}
            </Button>
          </Space>
        );
      },
    },
  ];

  // Tool list table column definitions
  const toolColumns = [
    {
      title: t("mcpConfig.toolsList.column.name"),
      dataIndex: "name",
      key: "name",
      width: "30%",
    },
    {
      title: t("mcpConfig.toolsList.column.description"),
      dataIndex: "description",
      key: "description",
      width: "70%",
      render: (text: string, record: McpTool) => {
        const isExpanded = expandedDescriptions.has(record.name);
        const maxLength = 100; // Show expand button when description exceeds 100 characters
        const needsExpansion = text && text.length > maxLength;

        return (
          <div>
            <div style={{ marginBottom: needsExpansion ? 8 : 0 }}>
              {needsExpansion && !isExpanded
                ? `${text.substring(0, maxLength)}...`
                : text}
            </div>
            {needsExpansion && (
              <Button
                type="link"
                size="small"
                icon={isExpanded ? <Minimize size={16} /> : <Maximize size={16} />}
                onClick={() => toggleDescription(record.name)}
                style={{ padding: 0, height: "auto" }}
              >
                {isExpanded
                  ? t("mcpConfig.toolsList.button.collapse")
                  : t("mcpConfig.toolsList.button.expand")}
              </Button>
            )}
          </div>
        );
      },
    },
  ];

  // Load container list
  const loadContainerList = async () => {
    setLoadingContainers(true);
    try {
      const result = await getMcpContainers();
      if (result.success) {
        setContainerList(result.data);
      } else {
        message.error(result.message);
      }
    } catch (error) {
      message.error(t("mcpConfig.message.loadContainerListFailed"));
    } finally {
      setLoadingContainers(false);
    }
  };

  // Add containerized MCP server
  const handleAddContainer = async () => {
    if (!containerConfigJson.trim()) {
      message.error(t("mcpConfig.message.containerConfigRequired"));
      return;
    }

    if (!containerPort || containerPort < 1 || containerPort > 65535) {
      message.error(t("mcpConfig.message.validPortRequired"));
      return;
    }

    let config;
    try {
      config = JSON.parse(containerConfigJson);
    } catch (error) {
      message.error(t("mcpConfig.message.invalidJsonConfig"));
      return;
    }

    // Validate config structure
    if (!config.mcpServers || typeof config.mcpServers !== "object") {
      message.error(t("mcpConfig.message.invalidConfigStructure"));
      return;
    }

    // Add port to each server config
    const configWithPorts = {
      mcpServers: Object.fromEntries(
        Object.entries(config.mcpServers).map(([key, value]: [string, any]) => [
          key,
          { ...value, port: containerPort },
        ])
      ),
    };

    // Schedule a delayed container refresh without waiting for creation to finish
    if (delayedContainerRefreshRef.current) {
      window.clearTimeout(delayedContainerRefreshRef.current);
    }
    delayedContainerRefreshRef.current = window.setTimeout(() => {
      loadContainerList().catch((error) => {
        log.error("Failed to refresh containers after add trigger:", error);
      });
    }, 3000);

    setAddingContainer(true);
    try {
      const result = await addMcpFromConfig(configWithPorts);
      if (result.success) {
        setContainerConfigJson("");
        setContainerPort(undefined);
        await loadContainerList();
        await loadServerList(); // Reload server list as containers are registered as servers

        // Refresh tools and agents
        await refreshToolsAndAgents();

        message.success(t("mcpService.message.addContainerSuccess"));
      } else {
        message.error(result.message);
      }
    } catch (error) {
      message.error(t("mcpConfig.message.addContainerFailed"));
    } finally {
      setAddingContainer(false);
    }
  };

  // View container logs
  const handleViewLogs = async (containerId: string) => {
    setCurrentContainerId(containerId);
    setLoadingLogs(true);
    setLogsModalVisible(true);
    setCurrentContainerLogs("");

    try {
      const result = await getMcpContainerLogs(containerId, 500);
      if (result.success) {
        setCurrentContainerLogs(result.data);
      } else {
        message.error(result.message);
        setCurrentContainerLogs(result.message);
      }
    } catch (error) {
      message.error(t("mcpConfig.message.getContainerLogsFailed"));
      setCurrentContainerLogs(t("mcpConfig.message.getContainerLogsFailed"));
    } finally {
      setLoadingLogs(false);
    }
  };

  // Delete container
  const handleDeleteContainer = async (container: McpContainer) => {
    confirm({
      title: t("mcpConfig.deleteContainer.confirmTitle"),
      content: t("mcpConfig.deleteContainer.confirmContent", {
        name: container.name || container.container_id,
      }),
      okText: t("common.delete", "Delete"),
      onOk: async () => {
        try {
          const result = await deleteMcpContainer(container.container_id);
          if (result.success) {
            await loadContainerList();
            await loadServerList(); // Reload server list as container is removed

            message.success(t("mcpService.message.deleteContainerSuccess"));

            // Refresh tools and agents
            refreshToolsAndAgents().catch((error) => {
              log.error(
                "Failed to refresh tools and agents after container deletion:",
                error
              );
            });
          } else {
            message.error(result.message);
            // Throw error to prevent modal from closing
            throw new Error(result.message);
          }
        } catch (error) {
          message.error(t("mcpConfig.message.deleteContainerFailed"));
          // Throw error to prevent modal from closing
          throw error;
        }
      },
    });
  };

  // Load data when modal opens
  useEffect(() => {
    if (visible) {
      loadServerList();
      loadContainerList();
    }
  }, [visible]);

  // Clear delayed refresh timer on unmount
  useEffect(() => {
    return () => {
      if (delayedContainerRefreshRef.current) {
        window.clearTimeout(delayedContainerRefreshRef.current);
      }
    };
  }, []);

  return (
    <>
      <Modal
        title={t("mcpConfig.modal.title")}
        open={visible}
        onCancel={actionsLocked ? undefined : onCancel}
        width={1000}
        closable={!actionsLocked}
        maskClosable={!actionsLocked}
        footer={[
          <Button key="cancel" onClick={onCancel} disabled={actionsLocked}>
            {actionsLocked
              ? t("mcpConfig.modal.updatingTools")
              : t("mcpConfig.modal.close")}
          </Button>,
        ]}
      >
        <div style={{ padding: "0 0 16px 0" }}>
          {/* Tool update status hint */}
          {updatingTools && (
            <div
              style={{
                marginBottom: 16,
                padding: 12,
                backgroundColor: "#f6ffed",
                border: "1px solid #b7eb8f",
                borderRadius: 6,
                display: "flex",
                alignItems: "center",
              }}
            >
              <LoaderCircle className="animate-spin" style={{ marginRight: 8, color: "#52c41a", width: 16, height: 16 }} />
              <Text style={{ color: "#52c41a" }}>
                {t("mcpConfig.status.updatingToolsHint")}
              </Text>
            </div>
          )}
          {/* Add server section */}
          <Card size="small" style={{ marginBottom: 16 }}>
            <Title level={5} style={{ margin: "0 0 12px 0" }}>
              {t("mcpConfig.addServer.title")}
            </Title>
            <Space orientation="vertical" style={{ width: "100%" }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <Input
                  placeholder={t("mcpConfig.addServer.namePlaceholder")}
                  value={newServerName}
                  onChange={(e) => setNewServerName(e.target.value)}
                  style={{ flex: 1 }}
                  maxLength={20}
                  disabled={actionsLocked || addingServer}
                />
                <Input
                  placeholder={t("mcpConfig.addServer.urlPlaceholder")}
                  value={newServerUrl}
                  onChange={(e) => setNewServerUrl(e.target.value)}
                  style={{ flex: 2 }}
                  disabled={actionsLocked || addingServer}
                />
                <Button
                  type="primary"
                  onClick={handleAddServer}
                  loading={addingServer || updatingTools}
                  icon={
                    addingServer || updatingTools ? (
                      <LoaderCircle className="animate-spin" style={{ width: 16, height: 16 }} />
                    ) : (
                      <Plus style={{ width: 16, height: 16 }} />
                    )
                  }
                  disabled={actionsLocked}
                >
                  {updatingTools
                    ? t("mcpConfig.addServer.button.updating")
                    : t("mcpConfig.addServer.button.add")}
                </Button>
              </div>
            </Space>
          </Card>

          {/* Add containerized MCP server section */}
          <Card size="small" style={{ marginBottom: 16 }}>
            <Title level={5} style={{ margin: "0 0 12px 0" }}>
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <Container style={{ width: 16, height: 16 }} />
                {t("mcpConfig.addContainer.title")}
              </span>
            </Title>
            <Space orientation="vertical" style={{ width: "100%" }} size="middle">
              <div>
                <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>
                  {t("mcpConfig.addContainer.configHint")}
                </Text>
                <Input.TextArea
                  placeholder={t("mcpConfig.addContainer.configPlaceholder")}
                  value={containerConfigJson}
                  onChange={(e) => setContainerConfigJson(e.target.value)}
                  rows={6}
                  disabled={actionsLocked}
                  style={{ fontFamily: "monospace", fontSize: 12 }}
                />
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <Text style={{ minWidth: 80 }}>{t("mcpConfig.addContainer.port")}:</Text>
                <Input
                  type="number"
                  placeholder={t("mcpConfig.addContainer.portPlaceholder")}
                  value={containerPort}
                  onChange={(e) => {
                    const port = parseInt(e.target.value);
                    setContainerPort(isNaN(port) ? undefined : port);
                  }}
                  min={1}
                  max={65535}
                  style={{ width: 150 }}
                  disabled={actionsLocked}
                />
                <div style={{ flex: 1 }} />
                <Button
                  type="primary"
                  onClick={handleAddContainer}
                  loading={addingContainer || updatingTools}
                  icon={
                    addingContainer || updatingTools ? (
                      <LoaderCircle className="animate-spin" size={16} />
                    ) : (
                      <Plus className="size-4" />
                    )
                  }
                  disabled={actionsLocked}
                >
                  {updatingTools
                    ? t("mcpConfig.addContainer.button.updating")
                    : t("mcpConfig.addContainer.button.add")}
                </Button>
              </div>
            </Space>
          </Card>

          <Divider style={{ margin: "16px 0" }} />

          {/* Server list */}
          <div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: 12,
              }}
            >
              <Title level={5} style={{ margin: 0 }}>
                {t("mcpConfig.serverList.title")}
              </Title>
            </div>
            <Table
              columns={columns}
              dataSource={serverList}
              rowKey={(record) => `${record.service_name}-${record.mcp_url}`}
              loading={loading}
              size="small"
              pagination={false}
              locale={{ emptyText: t("mcpConfig.serverList.empty") }}
              scroll={{ y: 300 }}
              style={{ width: "100%" }}
            />
          </div>

          {/* Container list */}
          <div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: 12,
              }}
            >
              <Title level={5} style={{ margin: 0 }}>
                {t("mcpConfig.containerList.title")}
              </Title>
            </div>
            <Table
              columns={[
                {
                  title: t("mcpConfig.containerList.column.name"),
                  dataIndex: "name",
                  key: "name",
                  width: "25%",
                  ellipsis: true,
                  render: (text: string, record: any) => text || record.container_id?.substring(0, 12),
                },
                {
                  title: t("mcpConfig.containerList.column.containerId"),
                  dataIndex: "container_id",
                  key: "container_id",
                  width: "20%",
                  ellipsis: true,
                  render: (text: string) => text || "-",
                },
                {
                  title: t("mcpConfig.containerList.column.port"),
                  dataIndex: "host_port",
                  key: "host_port",
                  width: "15%",
                  render: (port: number) => port || "-",
                },
                {
                  title: t("mcpConfig.containerList.column.status"),
                  dataIndex: "status",
                  key: "status",
                  width: "15%",
                  render: (status: string) => (
                    <span style={{ color: status === "running" ? "#52c41a" : "#ff4d4f" }}>
                      {status || "unknown"}
                    </span>
                  ),
                },
                {
                  title: t("mcpConfig.containerList.column.action"),
                  key: "action",
                  width: "25%",
                  render: (_: any, record: any) => (
                    <Space size="small">
                      <Button
                        type="link"
                        icon={<FileText className="size-4" />}
                        onClick={() => handleViewLogs(record.container_id)}
                        size="small"
                        disabled={updatingTools}
                      >
                        {t("mcpConfig.containerList.button.viewLogs")}
                      </Button>
                      <Button
                        type="link"
                        danger
                        icon={<Trash className="size-4" />}
                        onClick={() => handleDeleteContainer(record)}
                        size="small"
                        disabled={actionsLocked}
                      >
                        {t("mcpConfig.containerList.button.delete")}
                      </Button>
                    </Space>
                  ),
                },
              ]}
              dataSource={containerList}
              rowKey="container_id"
              loading={loadingContainers}
              size="small"
              pagination={false}
              locale={{ emptyText: t("mcpConfig.containerList.empty") }}
              scroll={{ y: 300 }}
              style={{ width: "100%" }}
            />
          </div>
        </div>
      </Modal>

      {/* Tool list modal */}
      <Modal
        title={`${currentServerName} - ${t("mcpConfig.toolsList.title")}`}
        open={toolsModalVisible}
        onCancel={() => setToolsModalVisible(false)}
        width={1000}
        footer={[
          <Button key="close" onClick={() => setToolsModalVisible(false)}>
            {t("mcpConfig.modal.close")}
          </Button>,
        ]}
      >
        <div style={{ padding: "0 0 16px 0" }}>
          {loadingTools ? (
            <div style={{ textAlign: "center", padding: "40px 0" }}>
              <LoaderCircle className="animate-spin" style={{ width: 16, height: 16, marginRight: 8, display: "inline-block" }} />
              <Text>{t("mcpConfig.toolsList.loading")}</Text>
            </div>
          ) : (
            <Table
              columns={toolColumns}
              dataSource={currentServerTools}
              rowKey="name"
              size="small"
              pagination={false}
              locale={{ emptyText: t("mcpConfig.toolsList.empty") }}
              scroll={{ y: 500 }}
              style={{ width: "100%" }}
            />
          )}
        </div>
      </Modal>

      {/* Container logs modal */}
      <Modal
        title={`${t("mcpConfig.containerLogs.title")} - ${currentContainerId?.substring(0, 12)}`}
        open={logsModalVisible}
        onCancel={() => setLogsModalVisible(false)}
        width={1000}
        footer={[
          <Button key="close" onClick={() => setLogsModalVisible(false)}>
            {t("mcpConfig.modal.close")}
          </Button>,
        ]}
      >
        <div style={{ padding: "0 0 16px 0" }}>
          {loadingLogs ? (
            <div style={{ textAlign: "center", padding: "40px 0" }}>
              <LoaderCircle className="animate-spin" size={16} />
              <Text>{t("mcpConfig.containerLogs.loading")}</Text>
            </div>
          ) : (
            <pre
              style={{
                backgroundColor: "#f5f5f5",
                padding: 16,
                borderRadius: 4,
                maxHeight: 500,
                overflow: "auto",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                fontSize: 12,
                fontFamily: "monospace",
              }}
            >
              {currentContainerLogs || t("mcpConfig.containerLogs.empty")}
            </pre>
          )}
        </div>
      </Modal>
    </>
  );
}
