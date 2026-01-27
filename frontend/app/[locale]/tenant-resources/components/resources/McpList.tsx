"use client";

import { useState, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  Modal,
  Button,
  Input,
  Table,
  Space,
  Typography,
  Card,
  Tooltip,
  App,
  Upload,
  Tabs,
  Popconfirm,
  Tag,
} from "antd";
import {
  Trash2,
  Eye,
  Plus,
  LoaderCircle,
  Maximize,
  Minimize,
  RefreshCw,
  FileText,
  Container,
  Upload as UploadIcon,
  Unplug,
  Edit,
  CircleCheck,
  CircleX,
  AlertCircle,
} from "lucide-react";
import { UploadFile } from "antd/es/upload/interface";

import {
  getMcpServerList,
  addMcpServer,
  updateMcpServer,
  deleteMcpServer,
  getMcpTools,
  updateToolList,
  checkMcpServerHealth,
  addMcpFromConfig,
  uploadMcpImage,
  getMcpContainers,
  getMcpContainerLogs,
  deleteMcpContainer,
} from "@/services/mcpService";
import { McpServer, McpTool, McpContainer, AgentRefreshEvent } from "@/types/agentConfig";
import log from "@/lib/logger";

const { Text, Title } = Typography;

export default function McpList({ tenantId }: { tenantId: string | null }) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  // List data
  const [serverList, setServerList] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(false);
  const [containerList, setContainerList] = useState<McpContainer[]>([]);
  
  // Add Modal State
  const [addModalVisible, setAddModalVisible] = useState(false);
  const [addingServer, setAddingServer] = useState(false);
  const [enableUploadImage, setEnableUploadImage] = useState(false);
  const [newServerName, setNewServerName] = useState("");
  const [newServerUrl, setNewServerUrl] = useState("");
  
  // Tools Modal State
  const [toolsModalVisible, setToolsModalVisible] = useState(false);
  const [currentServerTools, setCurrentServerTools] = useState<McpTool[]>([]);
  const [currentServerName, setCurrentServerName] = useState("");
  const [loadingTools, setLoadingTools] = useState(false);
  const [expandedDescriptions, setExpandedDescriptions] = useState<Set<string>>(new Set());

  // Edit Server State
  const [editServerModalVisible, setEditServerModalVisible] = useState(false);
  const [editingServer, setEditingServer] = useState<McpServer | null>(null);
  const [editServiceName, setEditServiceName] = useState("");
  const [editMcpUrl, setEditMcpUrl] = useState("");
  const [updatingServer, setUpdatingServer] = useState(false);

  // Common State
  const [updatingTools, setUpdatingTools] = useState(false);
  const [healthCheckLoading, setHealthCheckLoading] = useState<{ [key: string]: boolean }>({});

  // Container Add/Logs State
  const [addingContainer, setAddingContainer] = useState(false);
  const [containerConfigJson, setContainerConfigJson] = useState("");
  const [containerPort, setContainerPort] = useState<number | undefined>(undefined);
  const [logsModalVisible, setLogsModalVisible] = useState(false);
  const [currentContainerLogs, setCurrentContainerLogs] = useState("");
  const [currentContainerId, setCurrentContainerId] = useState("");
  const [loadingLogs, setLoadingLogs] = useState(false);
  const delayedContainerRefreshRef = useRef<number | undefined>(undefined);

  // Upload State
  const [uploadingImage, setUploadingImage] = useState(false);
  const [uploadFileList, setUploadFileList] = useState<UploadFile[]>([]);
  const [uploadPort, setUploadPort] = useState<number | undefined>(undefined);
  const [uploadServiceName, setUploadServiceName] = useState("");

  const actionsLocked = updatingTools || addingContainer || uploadingImage;

  // Helper function to refresh tools and agents
  const refreshToolsAndAgents = async () => {
    setUpdatingTools(true);
    try {
      const updateResult = await updateToolList();
      if (updateResult.success) {
        window.dispatchEvent(new CustomEvent("toolsUpdated"));
      }
      window.dispatchEvent(new CustomEvent("refreshAgentList") as AgentRefreshEvent);
    } catch (error) {
      log.error("Failed to refresh tools and agents:", error);
    } finally {
      setUpdatingTools(false);
    }
  };

  // Load MCP server list
  const loadServerList = async () => {
    setLoading(true);
    try {
      // Note: tenantId is not currently used by the API, but passed for future compatibility
      const result = await getMcpServerList();
      if (result.success) {
        setServerList(result.data);
        setEnableUploadImage(result.enable_upload_image || false);
      } else {
        message.error(result.message);
      }
    } catch (error) {
      message.error(t("mcpConfig.message.loadServerListFailed"));
    } finally {
      setLoading(false);
    }
  };

  // Load container list
  const loadContainerList = async () => {
    try {
      const result = await getMcpContainers();
      if (result.success) {
        setContainerList(result.data);
      } else {
        message.error(result.message);
      }
    } catch (error) {
      message.error(t("mcpConfig.message.loadContainerFailed"));
    }
  };

  // Initial load
  useEffect(() => {
    loadServerList();
    loadContainerList();
    return () => {
      if (delayedContainerRefreshRef.current) {
        window.clearTimeout(delayedContainerRefreshRef.current);
      }
    };
  }, [tenantId]);

  // Handlers (Add Server)
  const handleAddServer = async () => {
    if (!newServerName.trim() || !newServerUrl.trim()) {
      message.error(t("mcpConfig.message.completeServerInfo"));
      return;
    }
    const serverName = newServerName.trim();
    if (!/^[a-zA-Z0-9_-]+$/.test(serverName)) {
      message.error(t("mcpConfig.message.invalidServerName"));
      return;
    }
    if (serverName.length > 20) {
      message.error(t("mcpConfig.message.serverNameTooLong"));
      return;
    }
    if (serverList.some(s => s.service_name === serverName || s.mcp_url === newServerUrl.trim())) {
      message.error(t("mcpConfig.message.serverExists"));
      return;
    }

    setAddingServer(true);
    try {
      const result = await addMcpServer(newServerUrl.trim(), serverName);
      if (result.success) {
        setNewServerName("");
        setNewServerUrl("");
        await loadServerList();
        await refreshToolsAndAgents();
        queryClient.invalidateQueries({ queryKey: ["tools"] });
        queryClient.invalidateQueries({ queryKey: ["agents"] });
        message.success(t("mcpService.message.addServerSuccess"));
        setAddModalVisible(false);
      } else {
        message.error(result.message);
      }
    } catch (error) {
      message.error(t("mcpConfig.message.addServerFailed"));
    } finally {
      setAddingServer(false);
    }
  };

  // Handlers (Delete Server)
  const handleDeleteServer = async (server: McpServer) => {
    try {
      const result = await deleteMcpServer(server.mcp_url, server.service_name);
      if (result.success) {
        await loadServerList();
        message.success(t("mcpService.message.deleteServerSuccess"));
        refreshToolsAndAgents().catch(e => log.error("Refresh failed:", e));
        queryClient.invalidateQueries({ queryKey: ["tools"] });
        queryClient.invalidateQueries({ queryKey: ["agents"] });
      } else {
        message.error(result.message);
      }
    } catch (error) {
      message.error(t("mcpConfig.message.deleteServerFailed"));
    }
  };

  // Handlers (View Tools)
  const handleViewTools = async (server: McpServer) => {
    setCurrentServerName(server.service_name);
    setLoadingTools(true);
    setToolsModalVisible(true);
    setExpandedDescriptions(new Set());
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

  // Handlers (Health Check)
  const handleCheckHealth = async (server: McpServer) => {
    const key = `${server.service_name}__${server.mcp_url}`;
    message.info(t("mcpConfig.message.healthChecking", { name: server.service_name }));
    setHealthCheckLoading(prev => ({ ...prev, [key]: true }));
    try {
      const result = await checkMcpServerHealth(server.mcp_url, server.service_name);
      const isSuccess = result.success;
      if (isSuccess) message.success(t("mcpConfig.message.healthCheckSuccess"));
      else message.error(result.message || t("mcpConfig.message.healthCheckFailed"));
      
      await loadServerList();
      await refreshToolsAndAgents();
      queryClient.invalidateQueries({ queryKey: ["tools"] });
      queryClient.invalidateQueries({ queryKey: ["agents"] });
    } catch (error) {
      message.error(t("mcpConfig.message.healthCheckFailed"));
      await loadServerList();
      await refreshToolsAndAgents();
    } finally {
      setHealthCheckLoading(prev => ({ ...prev, [key]: false }));
    }
  };

  // Handlers (Edit Server)
  const handleEditServer = (server: McpServer) => {
    setEditingServer(server);
    setEditServiceName(server.service_name);
    setEditMcpUrl(server.mcp_url);
    setEditServerModalVisible(true);
  };

  const handleSaveEditedServer = async () => {
    if (!editingServer) return;
    if (!editServiceName.trim() || !editMcpUrl.trim()) {
      message.error(t("mcpConfig.message.nameAndUrlRequired"));
      return;
    }
    const serverName = editServiceName.trim();
    if (!/^[a-zA-Z0-9_-]+$/.test(serverName)) {
      message.error(t("mcpConfig.message.invalidServerName"));
      return;
    }
    if (serverName.length > 20) {
      message.error(t("mcpConfig.message.serverNameTooLong"));
      return;
    }

    setUpdatingServer(true);
    try {
      const result = await updateMcpServer(
        editingServer.service_name,
        editingServer.mcp_url,
        editServiceName.trim(),
        editMcpUrl.trim()
      );
      if (result.success) {
        message.success(t("mcpService.message.updateServerSuccess"));
        setEditServerModalVisible(false);
        setEditingServer(null);
        await loadServerList();
        // Optimistic update status
        setTimeout(() => {
          setServerList(prev => prev.map(s => 
            s.service_name === editServiceName.trim() && s.mcp_url === editMcpUrl.trim()
              ? { ...s, status: true } : s
          ));
        }, 300);
        await refreshToolsAndAgents();
        queryClient.invalidateQueries({ queryKey: ["tools"] });
        queryClient.invalidateQueries({ queryKey: ["agents"] });
      } else {
        message.error(result.message || t("mcpService.message.updateServerFailed"));
      }
    } catch (error) {
      message.error(t("mcpService.message.updateServerFailed"));
    } finally {
      setUpdatingServer(false);
    }
  };

  // Handlers (Container)
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
    if (!config.mcpServers || typeof config.mcpServers !== "object") {
      message.error(t("mcpConfig.message.invalidConfigStructure"));
      return;
    }

    const configWithPorts = {
      mcpServers: Object.fromEntries(
        Object.entries(config.mcpServers).map(([key, value]: [string, any]) => [
          key,
          { ...value, port: containerPort },
        ])
      ),
    };

    if (delayedContainerRefreshRef.current) {
      window.clearTimeout(delayedContainerRefreshRef.current);
    }
    delayedContainerRefreshRef.current = window.setTimeout(() => {
      loadContainerList().catch(e => log.error("Failed to refresh containers:", e));
    }, 3000);

    setAddingContainer(true);
    try {
      const result = await addMcpFromConfig(configWithPorts);
      if (result.success) {
        setContainerConfigJson("");
        setContainerPort(undefined);
        await loadContainerList();
        await loadServerList();
        await refreshToolsAndAgents();
        queryClient.invalidateQueries({ queryKey: ["tools"] });
        queryClient.invalidateQueries({ queryKey: ["agents"] });
        message.success(t("mcpService.message.addContainerSuccess"));
        setAddModalVisible(false);
      } else {
        message.error(result.message);
      }
    } catch (error) {
      message.error(t("mcpConfig.message.addContainerFailed"));
    } finally {
      setAddingContainer(false);
    }
  };

  const handleUploadImage = async () => {
    if (uploadFileList.length === 0) {
      message.error(t("mcpConfig.message.uploadImageFileRequired"));
      return;
    }
    if (!uploadPort || uploadPort < 1 || uploadPort > 65535) {
      message.error(t("mcpConfig.message.uploadImageValidPortRequired"));
      return;
    }
    const file = uploadFileList[0].originFileObj;
    if (!file) {
      message.error(t("mcpConfig.message.uploadImageFileRequired"));
      return;
    }
    if (!file.name.toLowerCase().endsWith(".tar")) {
      message.error(t("mcpConfig.message.uploadImageInvalidFileType"));
      return;
    }

    setUploadingImage(true);
    try {
      const result = await uploadMcpImage(file, uploadPort, uploadServiceName.trim() || undefined);
      if (result.success) {
        setUploadFileList([]);
        setUploadPort(undefined);
        setUploadServiceName("");
        await loadContainerList();
        await loadServerList();
        await refreshToolsAndAgents();
        queryClient.invalidateQueries({ queryKey: ["tools"] });
        queryClient.invalidateQueries({ queryKey: ["agents"] });
        message.success(t("mcpService.message.uploadImageSuccess"));
        setAddModalVisible(false);
      } else {
        message.error(result.message);
      }
    } catch (error) {
      message.error(t("mcpConfig.message.uploadImageFailed"));
    } finally {
      setUploadingImage(false);
    }
  };

  const handleDeleteContainer = async (container: McpContainer) => {
    try {
      const result = await deleteMcpContainer(container.container_id);
      if (result.success) {
        await loadContainerList();
        await loadServerList();
        message.success(t("mcpService.message.deleteContainerSuccess"));
        refreshToolsAndAgents().catch(e => log.error("Refresh failed:", e));
        queryClient.invalidateQueries({ queryKey: ["tools"] });
        queryClient.invalidateQueries({ queryKey: ["agents"] });
      } else {
        message.error(result.message);
      }
    } catch (error) {
      message.error(t("mcpConfig.message.deleteContainerFailed"));
    }
  };

  const handleViewLogs = async (containerId: string) => {
    setCurrentContainerId(containerId);
    setLoadingLogs(true);
    setLogsModalVisible(true);
    setCurrentContainerLogs("");
    try {
      const result = await getMcpContainerLogs(containerId, 500);
      if (result.success) setCurrentContainerLogs(result.data);
      else {
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

  // Columns for Server Table
  const serverColumns = [
    {
      title: t("mcpConfig.serverList.column.name"),
      dataIndex: "service_name",
      key: "service_name",
      width: "25%",
      ellipsis: true,
      render: (text: string) => (
        <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{text}</span>
      ),
    },
    {
      title: t("mcpConfig.serverList.column.url"),
      dataIndex: "mcp_url",
      key: "mcp_url",
      width: "35%",
      ellipsis: true,
    },
    {
      title: t("mcpConfig.serverList.column.status"),
      key: "status",
      width: "15%",
      render: (_: any, record: McpServer) => {
        const isAvailable = record.status;
        const key = `${record.service_name}__${record.mcp_url}`;
        return (
          <Tag
            color={isAvailable ? "success" : "error"}
            className="inline-flex items-center"
            variant="solid"
          >
            {healthCheckLoading[key] ? (
              <LoaderCircle className="animate-spin mr-1" size={12} />
            ) : isAvailable ? (
              <CircleCheck className="mr-1" size={12} />
            ) : (
              <CircleX className="mr-1" size={12} />
            )}
            {t(isAvailable ? "mcpConfig.status.available" : "mcpConfig.status.unavailable")}
          </Tag>
        );
      },
    },
    {
      title: t("mcpConfig.serverList.column.action"),
      key: "action",
      width: "25%",
      render: (_: any, record: McpServer) => {
        const key = `${record.service_name}__${record.mcp_url}`;
        return (
          <div className="flex items-center space-x-2">
            <Tooltip title={t("mcpConfig.serverList.button.healthCheck")}>
              <Button
                type="text"
                icon={<RefreshCw className={`h-4 w-4 ${healthCheckLoading[key] ? "animate-spin" : ""}`} />}
                onClick={() => handleCheckHealth(record)}
                size="small"
                loading={healthCheckLoading[key]}
                disabled={actionsLocked}
              />
            </Tooltip>
            <Tooltip title={!record.status ? t("mcpConfig.serverList.button.viewToolsDisabledHint") : t("mcpConfig.serverList.button.viewTools")}>
              <span>
                <Button
                  type="text"
                  icon={<Eye className="h-4 w-4" />}
                  onClick={() => handleViewTools(record)}
                  size="small"
                  disabled={!record.status || actionsLocked}
                />
              </span>
            </Tooltip>
            <Tooltip title={t("mcpConfig.serverList.button.edit")}>
              <Button
                type="text"
                icon={<Edit className="h-4 w-4" />}
                onClick={() => handleEditServer(record)}
                size="small"
                disabled={actionsLocked}
              />
            </Tooltip>
            <Popconfirm
              title={t("mcpConfig.delete.confirmTitle")}
              description={t("mcpConfig.delete.confirmContent", { name: record.service_name })}
              onConfirm={() => handleDeleteServer(record)}
              okText={t("common.delete")}
              cancelText={t("common.cancel")}
            >
              <Tooltip title={t("mcpConfig.serverList.button.delete")}>
                <Button
                  type="text"
                  danger
                  icon={<Trash2 className="h-4 w-4" />}
                  size="small"
                  disabled={actionsLocked}
                />
              </Tooltip>
            </Popconfirm>
          </div>
        );
      },
    },
  ];

  // Columns for Container Table
  const containerColumns = [
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
      render: (status: string) => {
        const statusConfig: Record<string, { color: string; icon: React.ReactNode }> = {
          running: { color: "success", icon: <CircleCheck size={12} /> },
          exited: { color: "error", icon: <CircleX size={12} /> },
          created: { color: "processing", icon: <LoaderCircle size={12} className="animate-spin" /> },
          paused: { color: "warning", icon: <AlertCircle size={12} /> },
          restarting: { color: "processing", icon: <LoaderCircle size={12} className="animate-spin" /> },
        };
        const config = statusConfig[status || ""] || { color: "default", icon: <AlertCircle size={12} /> };
        return (
          <Tag color={config.color} className="inline-flex items-center" variant="solid">
            <span className="mr-1">{config.icon}</span>
            {status || "unknown"}
          </Tag>
        );
      },
    },
    {
      title: t("mcpConfig.containerList.column.action"),
      key: "action",
      width: "25%",
      render: (_: any, record: any) => (
        <div className="flex items-center space-x-2">
          <Tooltip title={t("mcpConfig.containerList.button.viewLogs")}>
            <Button
              type="text"
              icon={<FileText className="h-4 w-4" />}
              onClick={() => handleViewLogs(record.container_id)}
              size="small"
              disabled={updatingTools}
            />
          </Tooltip>
          <Popconfirm
            title={t("mcpConfig.deleteContainer.confirmTitle")}
            description={t("mcpConfig.deleteContainer.confirmContent", { name: record.name || record.container_id })}
            onConfirm={() => handleDeleteContainer(record)}
            okText={t("common.delete")}
            cancelText={t("common.cancel")}
          >
            <Tooltip title={t("mcpConfig.containerList.button.delete")}>
              <Button
                type="text"
                danger
                icon={<Trash2 className="h-4 w-4" />}
                size="small"
                disabled={actionsLocked}
              />
            </Tooltip>
          </Popconfirm>
        </div>
      ),
    },
  ];

  const toolColumns = [
    { title: t("mcpConfig.toolsList.column.name"), dataIndex: "name", key: "name", width: "30%" },
    {
      title: t("mcpConfig.toolsList.column.description"),
      dataIndex: "description",
      key: "description",
      width: "70%",
      render: (text: string, record: McpTool) => {
        const isExpanded = expandedDescriptions.has(record.name);
        const maxLength = 100;
        const needsExpansion = text && text.length > maxLength;
        return (
          <div>
            <div style={{ marginBottom: needsExpansion ? 8 : 0 }}>
              {needsExpansion && !isExpanded ? `${text.substring(0, maxLength)}...` : text}
            </div>
            {needsExpansion && (
              <Button
                type="link"
                size="small"
                icon={isExpanded ? <Minimize size={16} /> : <Maximize size={16} />}
                onClick={() => {
                  const newExpanded = new Set(expandedDescriptions);
                  if (newExpanded.has(record.name)) newExpanded.delete(record.name);
                  else newExpanded.add(record.name);
                  setExpandedDescriptions(newExpanded);
                }}
                style={{ padding: 0, height: "auto" }}
              >
                {isExpanded ? t("mcpConfig.toolsList.button.collapse") : t("mcpConfig.toolsList.button.expand")}
              </Button>
            )}
          </div>
        );
      },
    },
  ];

  return (
    <div className="flex flex-col">
      <div className="flex justify-between items-center mb-4">
        <div />
        <Button type="primary" icon={<Plus size={16} />} onClick={() => setAddModalVisible(true)}>
          {t("tenantResources.mcp.addService")}
        </Button>
      </div>

      <div className="space-y-6">
        <div>
          <Title level={5} style={{ marginBottom: 12 }}>{t("mcpConfig.serverList.title")}</Title>
          <Table
            columns={serverColumns}
            dataSource={serverList}
            rowKey={(record) => `${record.service_name}-${record.mcp_url}`}
            loading={loading}
            size="small"
            pagination={{ pageSize: 7 }}
            locale={{ emptyText: t("mcpConfig.serverList.empty") }}
            scroll={{ x: true }}
          />
        </div>

        <div>
          <Title level={5} style={{ marginBottom: 12 }}>{t("mcpConfig.containerList.title")}</Title>
          <Table
            columns={containerColumns}
            dataSource={containerList}
            rowKey="container_id"
            loading={loading}
            size="small"
            pagination={{ pageSize: 3 }}
            locale={{ emptyText: t("mcpConfig.containerList.empty") }}
            scroll={{ x: true }}
          />
        </div>
      </div>

      {/* Add Modal */}
      <Modal
        title={t("mcpConfig.modal.title")}
        open={addModalVisible}
        onCancel={() => !actionsLocked && setAddModalVisible(false)}
        footer={null}
        width={800}
        destroyOnClose
      >
        <Tabs
          defaultActiveKey="remote"
          items={[
            {
              key: "remote",
              label: (
                <span className="flex items-center gap-2">
                  <Unplug size={16} />
                  {t("mcpConfig.addServer.title")}
                </span>
              ),
              children: (
                <Card size="small" className="mt-2">
                  <div className="flex items-center gap-2 w-full">
                    <Input
                      placeholder={t("mcpConfig.addServer.namePlaceholder")}
                      value={newServerName}
                      onChange={(e) => setNewServerName(e.target.value)}
                      maxLength={20}
                      disabled={actionsLocked || addingServer}
                      style={{ flex: 1 }}
                    />
                    <Input
                      placeholder={t("mcpConfig.addServer.urlPlaceholder")}
                      value={newServerUrl}
                      onChange={(e) => setNewServerUrl(e.target.value)}
                      disabled={actionsLocked || addingServer}
                      style={{ flex: 2 }}
                    />
                    <Button
                      type="primary"
                      onClick={handleAddServer}
                      loading={addingServer || updatingTools}
                      disabled={actionsLocked}
                      icon={addingServer || updatingTools ? <LoaderCircle className="animate-spin size-4" /> : <Plus className="size-4" />}
                    >
                      {t("mcpConfig.addServer.button.add")}
                    </Button>
                  </div>
                </Card>
              ),
            },
            {
              key: "container",
              label: (
                <span className="flex items-center gap-2">
                  <Container size={16} />
                  {t("mcpConfig.addContainer.title")}
                </span>
              ),
              children: (
                <Card size="small" className="mt-2">
                  <Space direction="vertical" className="w-full">
                    <Text type="secondary" style={{ fontSize: 12 }}>{t("mcpConfig.addContainer.configHint")}</Text>
                    <Input.TextArea
                      placeholder={t("mcpConfig.addContainer.configPlaceholder")}
                      value={containerConfigJson}
                      onChange={(e) => setContainerConfigJson(e.target.value)}
                      rows={6}
                      disabled={actionsLocked}
                      style={{ fontFamily: "monospace", fontSize: 12 }}
                    />
                    <div className="flex items-center gap-2">
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
                      <div className="flex-1" />
                      <Button
                        type="primary"
                        onClick={handleAddContainer}
                        loading={addingContainer || updatingTools}
                        disabled={actionsLocked}
                        icon={addingContainer || updatingTools ? <LoaderCircle className="animate-spin size-4" /> : <Plus className="size-4" />}
                      >
                        {t("mcpConfig.addContainer.button.add")}
                      </Button>
                    </div>
                  </Space>
                </Card>
              ),
            },
            ...(enableUploadImage ? [{
              key: "upload",
              label: (
                <span className="flex items-center gap-2">
                  <UploadIcon size={16} />
                  {t("mcpConfig.uploadImage.title")}
                </span>
              ),
              children: (
                <Card size="small" className="mt-2">
                  <Space direction="vertical" className="w-full">
                    <Text type="secondary" style={{ fontSize: 12 }}>{t("mcpConfig.uploadImage.fileHint")}</Text>
                    <Upload
                      fileList={uploadFileList}
                      onChange={({ fileList }) => setUploadFileList(fileList)}
                      beforeUpload={() => false}
                      accept=".tar"
                      maxCount={1}
                      disabled={actionsLocked}
                    >
                      <Button icon={<UploadIcon size={16} />} disabled={actionsLocked}>
                        {t("mcpConfig.uploadImage.button.selectFile")}
                      </Button>
                    </Upload>
                    <div className="flex items-center gap-2">
                      <Input
                        placeholder={t("mcpConfig.uploadImage.portPlaceholder")}
                        value={uploadPort || ""}
                        onChange={(e) => {
                            const val = parseInt(e.target.value);
                            if (e.target.value === "") setUploadPort(undefined);
                            else if (!isNaN(val) && val >= 1 && val <= 65535) setUploadPort(val);
                        }}
                        style={{ width: 150 }}
                        disabled={actionsLocked}
                        type="number"
                      />
                      <Input
                        placeholder={t("mcpConfig.uploadImage.serviceNamePlaceholder")}
                        value={uploadServiceName}
                        onChange={(e) => setUploadServiceName(e.target.value)}
                        className="flex-1"
                        disabled={actionsLocked}
                      />
                      <Button
                        type="primary"
                        onClick={handleUploadImage}
                        loading={uploadingImage || updatingTools}
                        disabled={actionsLocked}
                        icon={uploadingImage || updatingTools ? <LoaderCircle className="animate-spin size-4" /> : <Plus className="size-4" />}
                      >
                         {t("mcpConfig.addContainer.button.add")}
                      </Button>
                    </div>
                  </Space>
                </Card>
              ),
            }] : []),
          ]}
        />
      </Modal>

      {/* Tools Modal */}
      <Modal
        title={`${currentServerName} - ${t("mcpConfig.toolsList.title")}`}
        open={toolsModalVisible}
        onCancel={() => setToolsModalVisible(false)}
        width={800}
        footer={[<Button key="close" onClick={() => setToolsModalVisible(false)}>{t("mcpConfig.modal.close")}</Button>]}
      >
        {loadingTools ? (
          <div className="text-center py-10">
            <LoaderCircle className="animate-spin inline mr-2" size={16} />
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
          />
        )}
      </Modal>

      {/* Edit Server Modal */}
      <Modal
        title={t("mcpConfig.editServer.title")}
        open={editServerModalVisible}
        onCancel={() => setEditServerModalVisible(false)}
        onOk={handleSaveEditedServer}
        okButtonProps={{ loading: updatingServer }}
        okText={t("common.save")}
        cancelText={t("common.cancel")}
      >
        <Space direction="vertical" className="w-full">
            <div>
                <Text strong>{t("mcpConfig.editServer.serviceName")}</Text>
                <Input value={editServiceName} onChange={(e) => setEditServiceName(e.target.value)} className="mt-2" />
            </div>
            <div>
                <Text strong>{t("mcpConfig.editServer.mcpUrl")}</Text>
                <Input value={editMcpUrl} onChange={(e) => setEditMcpUrl(e.target.value)} className="mt-2" />
            </div>
        </Space>
      </Modal>

      {/* Logs Modal */}
      <Modal
        title={`${t("mcpConfig.containerLogs.title")} - ${currentContainerId?.substring(0, 12)}`}
        open={logsModalVisible}
        onCancel={() => setLogsModalVisible(false)}
        width={800}
        footer={[<Button key="close" onClick={() => setLogsModalVisible(false)}>{t("mcpConfig.modal.close")}</Button>]}
      >
        {loadingLogs ? (
          <div className="text-center py-10">
            <LoaderCircle className="animate-spin" size={16} />
            <Text>{t("mcpConfig.containerLogs.loading")}</Text>
          </div>
        ) : (
          <pre className="bg-gray-100 p-4 rounded max-h-[500px] overflow-auto whitespace-pre-wrap text-xs font-mono">
            {currentContainerLogs || t("mcpConfig.containerLogs.empty")}
          </pre>
        )}
      </Modal>
    </div>
  );
}

