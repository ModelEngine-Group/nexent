"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import {
  Modal,
  Button,
  Input,
  InputNumber,
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
  RefreshCw,
  FileText,
  Container,
  Upload as UploadIcon,
  Unplug,
  Edit,
  CheckCircle,
  CircleX,
  AlertCircle,
} from "lucide-react";
import { UploadFile } from "antd/es/upload/interface";

import { McpServer, McpTool, McpContainer } from "@/types/agentConfig";
import { useMcpConfig } from "@/hooks/useMcpConfig";
import McpToolListModal from "@/components/mcp/McpToolListModal";
import McpEditServerModal from "@/components/mcp/McpEditServerModal";
import McpContainerLogsModal from "@/components/mcp/McpContainerLogsModal";

const { Text, Title } = Typography;

export default function McpList({ tenantId }: { tenantId: string | null }) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  // Use shared hook for MCP config logic
  const {
    serverList,
    loading,
    containerList,
    enableUploadImage,
    updatingTools,
    healthCheckLoading,
    loadServerList,
    loadContainerList,
    handleAddServer,
    handleDeleteServer,
    handleViewTools,
    handleCheckHealth,
    handleUpdateServer,
    handleAddContainer,
    handleUploadImage,
    handleDeleteContainer,
    handleViewLogs,
  } = useMcpConfig({ enabled: true, tenantId });

  // Add Modal State
  const [addModalVisible, setAddModalVisible] = useState(false);
  const [addingServer, setAddingServer] = useState(false);
  const [newServerName, setNewServerName] = useState("");
  const [newServerUrl, setNewServerUrl] = useState("");

  // Tools Modal State
  const [toolsModalVisible, setToolsModalVisible] = useState(false);
  const [currentServerTools, setCurrentServerTools] = useState<McpTool[]>([]);
  const [currentServerName, setCurrentServerName] = useState("");
  const [loadingTools, setLoadingTools] = useState(false);

  // Edit Server State
  const [editServerModalVisible, setEditServerModalVisible] = useState(false);
  const [editingServer, setEditingServer] = useState<McpServer | null>(null);
  const [updatingServer, setUpdatingServer] = useState(false);

  // Container Add/Logs State
  const [addingContainer, setAddingContainer] = useState(false);
  const [containerConfigJson, setContainerConfigJson] = useState("");
  const [containerPort, setContainerPort] = useState<number | undefined>(undefined);
  const [logsModalVisible, setLogsModalVisible] = useState(false);
  const [currentContainerLogs, setCurrentContainerLogs] = useState("");
  const [currentContainerId, setCurrentContainerId] = useState("");
  const [loadingLogs, setLoadingLogs] = useState(false);

  // Upload State
  const [uploadingImage, setUploadingImage] = useState(false);
  const [uploadFileList, setUploadFileList] = useState<UploadFile[]>([]);
  const [uploadPort, setUploadPort] = useState<number | undefined>(undefined);
  const [uploadServiceName, setUploadServiceName] = useState("");

  const actionsLocked = updatingTools || addingContainer || uploadingImage;

  // Data loading is handled by React Query (enabled: true)

  // Handlers (Add Server)
  const onAddServer = async () => {
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
    const result = await handleAddServer(newServerUrl.trim(), serverName);
    if (result.success) {
      setNewServerName("");
      setNewServerUrl("");
      setAddModalVisible(false);
      message.success(result.messageKey ? t(result.messageKey) : t("mcpService.message.addServerSuccess"));
    } else {
      message.error(result.messageKey ? t(result.messageKey) : (result.message || t("mcpConfig.message.addServerFailed")));
    }
    setAddingServer(false);
  };

  // Handlers (Delete Server)
  const onDeleteServer = async (server: McpServer) => {
    const result = await handleDeleteServer(server);
    if (!result.success) {
      message.error(result.messageKey ? t(result.messageKey) : (result.message || t("mcpConfig.message.deleteServerFailed")));
    } else {
      message.success(result.messageKey ? t(result.messageKey) : t("mcpService.message.deleteServerSuccess"));
    }
  };

  // Handlers (View Tools)
  const onViewTools = async (server: McpServer) => {
    setCurrentServerName(server.service_name);
    setLoadingTools(true);
    setToolsModalVisible(true);

    const result = await handleViewTools(server);
    if (result.success) {
      setCurrentServerTools(result.data);
    } else {
      message.error(result.messageKey ? t(result.messageKey) : (result.message || t("mcpConfig.message.getToolsFailed")));
      setCurrentServerTools([]);
    }
    setLoadingTools(false);
  };

  // Handlers (Health Check)
  const onCheckHealth = async (server: McpServer) => {
    const key = "healthCheck";
    message.info({
      content: t("mcpConfig.message.healthChecking", {
        name: server.service_name,
      }),
      key,
    });

    try {
      const result = await handleCheckHealth(server);
      if (result.success) {
        message.success({
          content: result.messageKey
            ? t(result.messageKey)
            : t("mcpConfig.message.healthCheckSuccess"),
          key,
        });
      } else {
        message.error({
          content: result.messageKey
            ? t(result.messageKey)
            : result.message || t("mcpConfig.message.healthCheckFailed"),
          key,
        });
      }
    } catch (error) {
      message.error({
        content: t("mcpConfig.message.healthCheckFailed"),
        key,
      });
    }
  };

  // Handlers (Edit Server)
  const onEditServer = (server: McpServer) => {
    setEditingServer(server);
    setEditServerModalVisible(true);
  };

  const onSaveEditedServer = async (name: string, url: string) => {
    if (!editingServer) return;
    if (!name.trim() || !url.trim()) {
      message.error(t("mcpConfig.message.nameAndUrlRequired"));
      return;
    }
    const serverName = name.trim();
    if (!/^[a-zA-Z0-9_-]+$/.test(serverName)) {
      message.error(t("mcpConfig.message.invalidServerName"));
      return;
    }
    if (serverName.length > 20) {
      message.error(t("mcpConfig.message.serverNameTooLong"));
      return;
    }

    setUpdatingServer(true);
    const result = await handleUpdateServer(
      editingServer.service_name,
      editingServer.mcp_url,
      name.trim(),
      url.trim()
    );
    if (result.success) {
      setEditServerModalVisible(false);
      setEditingServer(null);
      message.success(result.messageKey ? t(result.messageKey) : t("mcpService.message.updateServerSuccess"));
    } else {
      message.error(result.messageKey ? t(result.messageKey) : (result.message || t("mcpService.message.updateServerFailed")));
    }
    setUpdatingServer(false);
  };

  // Handlers (Container)
  const onAddContainer = async () => {
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

    setAddingContainer(true);
    const result = await handleAddContainer(config, containerPort);
    if (result.success) {
      setContainerConfigJson("");
      setContainerPort(undefined);
      setAddModalVisible(false);
      message.success(result.messageKey ? t(result.messageKey) : t("mcpService.message.addContainerSuccess"));
    } else {
      message.error(result.messageKey ? t(result.messageKey) : (result.message || t("mcpConfig.message.addContainerFailed")));
    }
    setAddingContainer(false);
  };

  const onUploadImage = async () => {
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
    const result = await handleUploadImage(file, uploadPort, uploadServiceName.trim() || undefined);
    if (result.success) {
      setUploadFileList([]);
      setUploadPort(undefined);
      setUploadServiceName("");
      setAddModalVisible(false);
      message.success(result.messageKey ? t(result.messageKey) : t("mcpService.message.uploadImageSuccess"));
    } else {
      message.error(result.messageKey ? t(result.messageKey) : (result.message || t("mcpConfig.message.uploadImageFailed")));
    }
    setUploadingImage(false);
  };

  const onDeleteContainer = async (container: McpContainer) => {
    const result = await handleDeleteContainer(container);
    if (!result.success) {
      message.error(result.messageKey ? t(result.messageKey) : (result.message || t("mcpConfig.message.deleteContainerFailed")));
    } else {
      message.success(result.messageKey ? t(result.messageKey) : t("mcpService.message.deleteContainerSuccess"));
    }
  };

  const onViewLogs = async (containerId: string) => {
    setCurrentContainerId(containerId);
    setLoadingLogs(true);
    setLogsModalVisible(true);
    setCurrentContainerLogs("");

    const result = await handleViewLogs(containerId, 500);
    if (result.success) {
      setCurrentContainerLogs(result.data);
    } else {
      message.error(result.messageKey ? t(result.messageKey) : t("mcpConfig.message.getContainerLogsFailed"));
      setCurrentContainerLogs(t("mcpConfig.message.getContainerLogsFailed"));
    }
    setLoadingLogs(false);
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
            color={healthCheckLoading[key] ? "#2E4053" : isAvailable ? "#229954" : "#E74C3C"}
            className="inline-flex items-center"
            variant="solid"
          >
            {healthCheckLoading[key] ? (
              <LoaderCircle className="w-3 h-3 animate-spin mr-1" />
            ) : isAvailable ? (
              <CheckCircle className="w-3 h-3 mr-1" />
            ) : (
              <CircleX className="w-3 h-3 mr-1" />
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
                onClick={() => onCheckHealth(record)}
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
                  onClick={() => onViewTools(record)}
                  size="small"
                  disabled={!record.status || actionsLocked}
                />
              </span>
            </Tooltip>
            <Tooltip title={t("mcpConfig.serverList.button.edit")}>
              <Button
                type="text"
                icon={<Edit className="h-4 w-4" />}
                onClick={() => onEditServer(record)}
                size="small"
                disabled={actionsLocked}
              />
            </Tooltip>
            <Popconfirm
              title={t("mcpConfig.delete.confirmTitle")}
              description={t("mcpConfig.delete.confirmContent", { name: record.service_name })}
              onConfirm={() => onDeleteServer(record)}
              okText={t("common.confirm")}
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
          running: { color: "#229954", icon: <CheckCircle className="w-3 h-3" /> },
          exited: { color: "#E74C3C", icon: <CircleX className="w-3 h-3" /> },
          created: { color: "#2E4053", icon: <LoaderCircle className="w-3 h-3 animate-spin" /> },
          paused: { color: "#AEB6BF", icon: <AlertCircle className="w-3 h-3" /> },
          restarting: { color: "#2E4053", icon: <LoaderCircle className="w-3 h-3 animate-spin" /> },
        };
        const config = statusConfig[status || ""] || { color: "#2E4053", icon: <AlertCircle className="w-3 h-3" /> };
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
              onClick={() => onViewLogs(record.container_id)}
              size="small"
              disabled={updatingTools}
            />
          </Tooltip>
          <Popconfirm
            title={t("mcpConfig.deleteContainer.confirmTitle")}
            description={t("mcpConfig.deleteContainer.confirmContent", { name: record.name || record.container_id })}
            onConfirm={() => onDeleteContainer(record)}
            okText={t("common.confirm")}
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

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex justify-between items-center mb-4 flex-shrink-0">
        <div />
        <Button type="primary" icon={<Plus size={16} />} onClick={() => setAddModalVisible(true)}>
          {t("tenantResources.mcp.addService")}
        </Button>
      </div>

      <div className="space-y-6 flex-1 overflow-auto">
        <div className="min-w-0">
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

        <div className="min-w-0">
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
                      onClick={onAddServer}
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
                      <InputNumber
                        placeholder={t("mcpConfig.addContainer.portPlaceholder")}
                        value={containerPort}
                        onChange={(value) => {
                          setContainerPort(value === null ? undefined : value);
                        }}
                        min={1}
                        max={65535}
                        style={{ width: 150 }}
                        disabled={actionsLocked}
                        controls={false}
                      />
                      <div className="flex-1" />
                      <Button
                          type="primary"
                          onClick={onAddContainer}
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
                      <InputNumber
                        placeholder={t("mcpConfig.uploadImage.portPlaceholder")}
                        value={uploadPort}
                        onChange={(value) => {
                            setUploadPort(value === null ? undefined : value);
                        }}
                        style={{ width: 150 }}
                        disabled={actionsLocked}
                        min={1}
                        max={65535}
                        controls={false}
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
                        onClick={onUploadImage}
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
      <McpToolListModal
        open={toolsModalVisible}
        onCancel={() => setToolsModalVisible(false)}
        loading={loadingTools}
        tools={currentServerTools}
        serverName={currentServerName}
      />

      {/* Edit Server Modal */}
      <McpEditServerModal
        open={editServerModalVisible}
        onCancel={() => setEditServerModalVisible(false)}
        onSave={onSaveEditedServer}
        initialName={editingServer?.service_name || ""}
        initialUrl={editingServer?.mcp_url || ""}
        loading={updatingServer}
      />

      {/* Logs Modal */}
      <McpContainerLogsModal
        open={logsModalVisible}
        onCancel={() => setLogsModalVisible(false)}
        loading={loadingLogs}
        logs={currentContainerLogs}
        containerId={currentContainerId}
      />
    </div>
  );
}
