"use client";

import { useState, useEffect } from "react";
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
  DeleteOutlined,
  EyeOutlined,
  PlusOutlined,
  LoadingOutlined,
  ExpandAltOutlined,
  CompressOutlined,
  RedoOutlined,
} from "@ant-design/icons";

import { McpConfigModalProps, AgentRefreshEvent } from "@/types/agentConfig";
import {
  getMcpServerList,
  addMcpServer,
  deleteMcpServer,
  getMcpTools,
  updateToolList,
  checkMcpServerHealth,
} from "@/services/mcpService";
import { McpServer, McpTool } from "@/types/agentConfig";
import log from "@/lib/logger";

const { Text, Title } = Typography;

export default function McpConfigModal({
  visible,
  onCancel,
}: McpConfigModalProps) {
  const { t } = useTranslation("common");
  const { message, modal } = App.useApp();
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
    modal.confirm({
      title: t("mcpConfig.delete.confirmTitle"),
      content: t("mcpConfig.delete.confirmContent", {
        name: server.service_name,
      }),
      okText: t("common.delete", "Delete"),
      cancelText: t("common.cancel", "Cancel"),
      okType: "danger",
      cancelButtonProps: { disabled: updatingTools },
      okButtonProps: { disabled: updatingTools, loading: updatingTools },
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
                <LoadingOutlined
                  style={{ color: record.status ? "#52c41a" : "#ff4d4f" }}
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
              icon={<RedoOutlined />}
              onClick={() => handleCheckHealth(record)}
              size="small"
              loading={healthCheckLoading[key]}
              disabled={updatingTools}
            >
              {t("mcpConfig.serverList.button.healthCheck")}
            </Button>
            {record.status ? (
              <Button
                type="link"
                icon={<EyeOutlined />}
                onClick={() => handleViewTools(record)}
                size="small"
                disabled={updatingTools}
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
                  icon={<EyeOutlined />}
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
              icon={<DeleteOutlined />}
              onClick={() => handleDeleteServer(record)}
              size="small"
              disabled={updatingTools}
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
                icon={isExpanded ? <CompressOutlined /> : <ExpandAltOutlined />}
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

  // Load data when modal opens
  useEffect(() => {
    if (visible) {
      loadServerList();
    }
  }, [visible]);

  return (
    <>
      <Modal
        title={t("mcpConfig.modal.title")}
        open={visible}
        onCancel={updatingTools ? undefined : onCancel}
        width={1000}
        closable={!updatingTools}
        maskClosable={!updatingTools}
        footer={[
          <Button key="cancel" onClick={onCancel} disabled={updatingTools}>
            {updatingTools
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
              <LoadingOutlined style={{ marginRight: 8, color: "#52c41a" }} />
              <Text style={{ color: "#52c41a" }}>
                {t("mcpConfig.status.updatingToolsHint")}
              </Text>
            </div>
          )}
          {/* Add server section */}
          <Card size="small" style={{ marginBottom: 16 }}>
            <Title level={5} style={{ margin: "0 0 12px 0" }}>
              <PlusOutlined style={{ marginRight: 8 }} />
              {t("mcpConfig.addServer.title")}
            </Title>
            <Space direction="vertical" style={{ width: "100%" }}>
              <div style={{ display: "flex", gap: 8 }}>
                <Input
                  placeholder={t("mcpConfig.addServer.namePlaceholder")}
                  value={newServerName}
                  onChange={(e) => setNewServerName(e.target.value)}
                  style={{ flex: 1 }}
                  maxLength={20}
                  disabled={updatingTools || addingServer}
                />
                <Input
                  placeholder={t("mcpConfig.addServer.urlPlaceholder")}
                  value={newServerUrl}
                  onChange={(e) => setNewServerUrl(e.target.value)}
                  style={{ flex: 2 }}
                  disabled={updatingTools || addingServer}
                />
                <Button
                  type="primary"
                  onClick={handleAddServer}
                  loading={addingServer || updatingTools}
                  icon={
                    addingServer || updatingTools ? (
                      <LoadingOutlined />
                    ) : (
                      <PlusOutlined />
                    )
                  }
                  disabled={updatingTools}
                >
                  {updatingTools
                    ? t("mcpConfig.addServer.button.updating")
                    : t("mcpConfig.addServer.button.add")}
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
              <LoadingOutlined style={{ fontSize: 24, marginRight: 8 }} />
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
    </>
  );
}
