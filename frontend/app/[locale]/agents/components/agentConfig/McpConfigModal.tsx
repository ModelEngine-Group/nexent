"use client";

import { useState, useEffect, type ComponentProps } from "react";
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
  Divider,
  Tooltip,
  App,
  Upload,
  Tabs,
} from "antd";
import {
  Trash,
  Eye,
  Plus,
  LoaderCircle,
  RefreshCw,
  FileText,
  Container,
  Upload as UploadIcon,
  Unplug,
  Settings,
} from "lucide-react";

import { McpConfigModalProps } from "@/types/agentConfig";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { UploadFile } from "antd/es/upload/interface";
import { useMcpConfig } from "@/hooks/useMcpConfig";
import McpToolListModal from "@/components/mcp/McpToolListModal";
import McpEditServerModal from "@/components/mcp/McpEditServerModal";
import McpContainerLogsModal from "@/components/mcp/McpContainerLogsModal";

const { Text, Title } = Typography;

export default function McpConfigModal({
  visible,
  onCancel,
  }: McpConfigModalProps) {
  const { t } = useTranslation("common");
  const { confirm } = useConfirmModal();
  const { message, modal } = App.useApp();

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
  } = useMcpConfig({ enabled: visible });

  // Local UI state
  const [addingServer, setAddingServer] = useState(false);
  const [newServerName, setNewServerName] = useState("");
  const [newServerUrl, setNewServerUrl] = useState("");

  const [toolsModalVisible, setToolsModalVisible] = useState(false);
  const [currentServerTools, setCurrentServerTools] = useState<any[]>([]);
  const [currentServerName, setCurrentServerName] = useState("");
  const [loadingTools, setLoadingTools] = useState(false);

  const [editServerModalVisible, setEditServerModalVisible] = useState(false);
  const [editingServer, setEditingServer] = useState<any>(null);
  const [updatingServer, setUpdatingServer] = useState(false);

  const [addingContainer, setAddingContainer] = useState(false);
  const [containerConfigJson, setContainerConfigJson] = useState("");
  const [containerPort, setContainerPort] = useState<number | undefined>(
    undefined
  );

  const [logsModalVisible, setLogsModalVisible] = useState(false);
  const [currentContainerLogs, setCurrentContainerLogs] = useState("");
  const [currentContainerId, setCurrentContainerId] = useState("");
  const [loadingLogs, setLoadingLogs] = useState(false);

  const [uploadingImage, setUploadingImage] = useState(false);
  const [uploadFileList, setUploadFileList] = useState<UploadFile[]>([]);
  const [uploadPort, setUploadPort] = useState<number | undefined>(undefined);
  const [uploadServiceName, setUploadServiceName] = useState("");

  const actionsLocked = updatingTools || addingContainer || uploadingImage;
  const noMcpEditPermissionTitle = t("mcpConfig.permission.noEdit");

  const renderPermissionControlledButton = (props: {
    isReadOnly: boolean;
    button: Omit<ComponentProps<typeof Button>, "disabled" | "onClick"> & {
      disabled?: boolean;
      onClick?: (() => void) | undefined;
    };
  }) => {
    const { isReadOnly, button } = props;
    const { onClick, disabled, ...rest } = button;

    const finalDisabled = Boolean(disabled) || isReadOnly;
    const finalOnClick = finalDisabled ? undefined : onClick;

    const element = (
      <Button
        {...rest}
        onClick={finalOnClick}
        disabled={finalDisabled}
      />
    );

    if (!isReadOnly) return element;

    return (
      <Tooltip title={noMcpEditPermissionTitle}>
        <span style={{ display: "inline-flex" }}>{element}</span>
      </Tooltip>
    );
  };

  // Data loading is handled by React Query (enabled: visible)

  // Handlers
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

    if (serverList.some((s) => s.service_name === serverName || s.mcp_url === newServerUrl.trim())) {
      message.error(t("mcpConfig.message.serverExists"));
      return;
    }

    setAddingServer(true);
    const result = await handleAddServer(newServerUrl.trim(), serverName);
    if (result.success) {
      setNewServerName("");
      setNewServerUrl("");
      message.success(result.messageKey ? t(result.messageKey) : t("mcpService.message.addServerSuccess"));
    } else {
      message.error(result.messageKey ? t(result.messageKey) : (result.message || t("mcpConfig.message.addServerFailed")));
    }
    setAddingServer(false);
  };

  const onDeleteServer = (server: any) => {
    confirm({
      title: t("mcpConfig.delete.confirmTitle"),
      content: t("mcpConfig.delete.confirmContent", {
        name: server.service_name,
      }),
      okText: t("common.delete", "Delete"),
      onOk: async () => {
        const result = await handleDeleteServer(server);
        if (!result.success) {
          message.error(
            result.messageKey
              ? t(result.messageKey)
              : result.message || t("mcpConfig.message.deleteServerFailed")
          );
        } else {
          message.success(
            result.messageKey
              ? t(result.messageKey)
              : t("mcpService.message.deleteServerSuccess")
          );
        }
      },
    });
  };

  const onViewTools = async (server: any) => {
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

  const onCheckHealth = async (server: any) => {
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

  const onEditServer = (server: any) => {
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
    } catch {
      message.error(t("mcpConfig.message.invalidJsonConfig"));
      return;
    }

    if (!config.mcpServers || typeof config.mcpServers !== "object") {
      message.error(t("mcpConfig.message.invalidConfigStructure"));
      return;
    }

    setAddingContainer(true);
    const result = await handleAddContainer(config, containerPort);
    if (!result.success) {
      message.error(result.messageKey ? t(result.messageKey) : (result.message || t("mcpConfig.message.addContainerFailed")));
    } else {
      setContainerConfigJson("");
      setContainerPort(undefined);
      message.success(result.messageKey ? t(result.messageKey) : t("mcpService.message.addContainerSuccess"));
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
    if (!result.success) {
      message.error(result.messageKey ? t(result.messageKey) : (result.message || t("mcpConfig.message.uploadImageFailed")));
    } else {
      setUploadFileList([]);
      setUploadPort(undefined);
      setUploadServiceName("");
      message.success(result.messageKey ? t(result.messageKey) : t("mcpService.message.uploadImageSuccess"));
    }
    setUploadingImage(false);
  };

  const onDeleteContainer = (container: any) => {
    confirm({
      title: t("mcpConfig.deleteContainer.confirmTitle"),
      content: t("mcpConfig.deleteContainer.confirmContent", {
        name: container.name || container.container_id,
      }),
      okText: t("common.delete", "Delete"),
      onOk: async () => {
        const result = await handleDeleteContainer(container);
        if (!result.success) {
          message.error(
            result.messageKey
              ? t(result.messageKey)
              : result.message || t("mcpConfig.message.deleteContainerFailed")
          );
        } else {
          message.success(
            result.messageKey
              ? t(result.messageKey)
              : t("mcpService.message.deleteContainerSuccess")
          );
        }
      },
    });
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

  // Server list table columns
  const serverColumns = [
    {
      title: t("mcpConfig.serverList.column.name"),
      dataIndex: "service_name",
      key: "service_name",
      width: "25%",
      ellipsis: true,
      render: (text: string) => (
        <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
          {text}
        </span>
      ),
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
      render: (_: any, record: any) => {
        const key = `${record.service_name}__${record.mcp_url}`;
        const isReadOnly = record.permission === "READ_ONLY";
        return (
          <Space size="small">
            <Button
              type="link"
              icon={
                <RefreshCw
                  size={16}
                  className={healthCheckLoading[key] ? "animate-spin" : ""}
                />
              }
              onClick={() => onCheckHealth(record)}
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
                onClick={() => onViewTools(record)}
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
                  <span style={{ display: "inline-flex" }}>
                    <Button type="link" icon={<Eye size={16} />} size="small" disabled>
                      {t("mcpConfig.serverList.button.viewTools")}
                    </Button>
                  </span>
              </Tooltip>
            )}
            {renderPermissionControlledButton({
              isReadOnly,
              button: {
                type: "link",
                icon: <Settings size={16} />,
                onClick: () => onEditServer(record),
                size: "small",
                disabled: actionsLocked,
                children: t("mcpConfig.serverList.button.edit"),
              },
            })}
            {renderPermissionControlledButton({
              isReadOnly,
              button: {
                type: "link",
                danger: true,
                icon: <Trash size={16} />,
                onClick: () => onDeleteServer(record),
                size: "small",
                disabled: actionsLocked,
                children: t("mcpConfig.serverList.button.delete"),
              },
            })}
          </Space>
        );
      },
    },
  ];

  // Container list table columns
  const containerColumns = [
    {
      title: t("mcpConfig.containerList.column.name"),
      dataIndex: "name",
      key: "name",
      width: "25%",
      ellipsis: true,
      render: (text: string, record: any) =>
        text || record.container_id?.substring(0, 12),
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
        <span
          style={{
            color: status === "running" ? "#52c41a" : "#ff4d4f",
          }}
        >
          {status || "unknown"}
        </span>
      ),
    },
    {
      title: t("mcpConfig.containerList.column.action"),
      key: "action",
      width: "25%",
      render: (_: any, record: any) => {
        const isReadOnly = record.permission === "READ_ONLY";
        return (
          <Space size="small">
            <Button
              type="link"
              icon={<FileText className="size-4" />}
              onClick={() => onViewLogs(record.container_id)}
              size="small"
              disabled={updatingTools}
            >
              {t("mcpConfig.containerList.button.viewLogs")}
            </Button>
            {renderPermissionControlledButton({
              isReadOnly,
              button: {
                type: "link",
                danger: true,
                icon: <Trash className="size-4" />,
                onClick: () => onDeleteContainer(record),
                size: "small",
                disabled: actionsLocked,
                children: t("mcpConfig.containerList.button.delete"),
              },
            })}
          </Space>
        );
      },
    },
  ];

  return (
    <>
      <Modal
        title={t("mcpConfig.modal.title")}
        open={visible}
        onCancel={actionsLocked ? undefined : onCancel}
        width={1200}
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
              <LoaderCircle
                className="animate-spin"
                style={{
                  marginRight: 8,
                  color: "#52c41a",
                  width: 16,
                  height: 16,
                }}
              />
              <Text style={{ color: "#52c41a" }}>
                {t("mcpConfig.status.updatingToolsHint")}
              </Text>
            </div>
          )}

          {/* Add MCP server tabs */}
          <Tabs
            defaultActiveKey="remote"
            size="small"
            style={{ marginBottom: 16 }}
            items={[
              {
                key: "remote",
                label: (
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 8,
                    }}
                  >
                    <Unplug style={{ width: 16, height: 16 }} />
                    {t("mcpConfig.addServer.title")}
                  </span>
                ),
                children: (
                  <Card size="small" style={{ marginTop: 8 }}>
                    <Space orientation="vertical" style={{ width: "100%" }}>
                      <div
                        style={{
                          display: "flex",
                          gap: 8,
                          alignItems: "center",
                        }}
                      >
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
                          onClick={onAddServer}
                          loading={addingServer || updatingTools}
                          icon={
                            addingServer || updatingTools ? (
                              <LoaderCircle
                                className="animate-spin"
                                style={{ width: 16, height: 16 }}
                              />
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
                ),
              },
              {
                key: "container",
                label: (
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
                ),
                children: (
                  <Card size="small" style={{ marginTop: 8 }}>
                    <Space
                      orientation="vertical"
                      style={{ width: "100%" }}
                      size="middle"
                    >
                      <div>
                        <Text
                          type="secondary"
                          style={{
                            fontSize: 12,
                            display: "block",
                            marginBottom: 8,
                          }}
                        >
                          {t("mcpConfig.addContainer.configHint")}
                        </Text>
                        <Input.TextArea
                          placeholder={t(
                            "mcpConfig.addContainer.configPlaceholder"
                          )}
                          value={containerConfigJson}
                          onChange={(e) =>
                            setContainerConfigJson(e.target.value)
                          }
                          rows={6}
                          disabled={actionsLocked}
                          style={{ fontFamily: "monospace", fontSize: 12 }}
                        />
                      </div>
                      <div
                        style={{
                          display: "flex",
                          gap: 8,
                          alignItems: "center",
                        }}
                      >
                        <Text style={{ minWidth: 80 }}>
                          {t("mcpConfig.addContainer.port")}:
                        </Text>
                        <InputNumber
                          placeholder={t(
                            "mcpConfig.addContainer.portPlaceholder"
                          )}
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
                        <div style={{ flex: 1 }} />
                        <Button
                          type="primary"
                          onClick={onAddContainer}
                          loading={addingContainer || updatingTools}
                          icon={
                            addingContainer || updatingTools ? (
                              <LoaderCircle
                                className="animate-spin"
                                size={16}
                              />
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
                ),
              },
              ...(enableUploadImage
                ? [
                    {
                      key: "upload",
                      label: (
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 8,
                          }}
                        >
                          <UploadIcon style={{ width: 16, height: 16 }} />
                          {t("mcpConfig.uploadImage.title")}
                        </span>
                      ),
                      children: (
                        <Card size="small" style={{ marginTop: 8 }}>
                          <Space
                            direction="vertical"
                            style={{ width: "100%" }}
                            size="middle"
                          >
                            <div>
                              <Text
                                type="secondary"
                                style={{
                                  fontSize: 12,
                                  display: "block",
                                  marginBottom: 8,
                                }}
                              >
                                {t("mcpConfig.uploadImage.fileHint")}
                              </Text>
                              <Upload
                                fileList={uploadFileList}
                                onChange={({ fileList }) =>
                                  setUploadFileList(fileList)
                                }
                                beforeUpload={() => false}
                                accept=".tar"
                                maxCount={1}
                                disabled={actionsLocked}
                              >
                                <Button
                                  icon={<UploadIcon size={16} />}
                                  disabled={actionsLocked}
                                >
                                  {t("mcpConfig.uploadImage.button.selectFile")}
                                </Button>
                              </Upload>
                            </div>
                            <div
                              style={{
                                display: "flex",
                                gap: 8,
                                alignItems: "center",
                              }}
                            >
                              <InputNumber
                                placeholder={t(
                                  "mcpConfig.uploadImage.portPlaceholder"
                                )}
                                value={uploadPort}
                                onChange={(value) => {
                                  setUploadPort(value === null ? undefined : value);
                                }}
                                min={1}
                                max={65535}
                                style={{ width: 150 }}
                                disabled={actionsLocked}
                                controls={false}
                              />
                              <Input
                                placeholder={t(
                                  "mcpConfig.uploadImage.serviceNamePlaceholder"
                                )}
                                value={uploadServiceName}
                                onChange={(e) =>
                                  setUploadServiceName(e.target.value)
                                }
                                style={{ flex: 1 }}
                                disabled={actionsLocked}
                              />
                              <Button
                                type="primary"
                                onClick={onUploadImage}
                                loading={uploadingImage || updatingTools}
                                icon={
                                  uploadingImage || updatingTools ? (
                                    <LoaderCircle
                                      className="animate-spin"
                                      size={16}
                                    />
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
                      ),
                    },
                  ]
                : []),
            ]}
          />

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
              columns={serverColumns}
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
              columns={containerColumns}
              dataSource={containerList}
              rowKey="container_id"
              loading={loading}
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
      <McpToolListModal
        open={toolsModalVisible}
        onCancel={() => setToolsModalVisible(false)}
        loading={loadingTools}
        tools={currentServerTools}
        serverName={currentServerName}
      />

      {/* Edit server modal */}
      <McpEditServerModal
        open={editServerModalVisible}
        onCancel={() => setEditServerModalVisible(false)}
        onSave={onSaveEditedServer}
        initialName={editingServer?.service_name || ""}
        initialUrl={editingServer?.mcp_url || ""}
        loading={updatingServer}
      />

      {/* Container logs modal */}
      <McpContainerLogsModal
        open={logsModalVisible}
        onCancel={() => setLogsModalVisible(false)}
        loading={loadingLogs}
        logs={currentContainerLogs}
        containerId={currentContainerId}
      />
    </>
  );
}
