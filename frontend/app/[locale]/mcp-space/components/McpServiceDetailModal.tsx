import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
} from "antd";
import {
  ApiOutlined,
  CloudOutlined,
  ContainerOutlined,
  LinkOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import {
  McpDeploymentType,
  McpServiceStatus,
  McpTransportType,
  MCP_ADD_SERVICE_MODAL_WIDTH_MARKETS,
  MCP_TOOLS_MODAL_WRAP_CLASS,
  mcpToolsModalChromeStyles,
} from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";
import { resolveDeploymentType, toPrettyRegistryJson } from "@/lib/mcpTools";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import { useMcpServiceDetail } from "@/hooks/mcpTools/useMcpServiceDetail";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { Can } from "@/components/permission/Can";
import McpContainerLogsModal from "@/components/mcp/McpContainerLogsModal";
import McpToolListModal from "@/components/mcp/McpToolListModal";
import ContainerPortField from "./shared/ContainerPortField";
import ResourceTagAssignmentModal from "@/components/tag/ResourceTagAssignmentModal";
import ResourceTagChips from "@/components/tag/ResourceTagChips";
import TagDefinitionManagementModal from "@/components/tag/TagDefinitionManagementModal";
import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";
import JsonPreviewModal from "./shared/JsonPreviewModal";
import PublishConfirmModal from "./PublishConfirmModal";

interface McpServiceDetailModalProps {
  selectedService: McpServiceItem | null;
  onClose: () => void;
  onToggled?: (mcpId: number, next: McpServiceStatus) => void;
}

const DEPLOYMENT_OPTIONS = [
  {
    value: McpDeploymentType.REMOTE_LINK,
    labelKey: "mcpTools.deploymentType.remoteLink",
    Icon: LinkOutlined,
  },
  {
    value: McpDeploymentType.CONTAINER,
    labelKey: "mcpTools.deploymentType.container",
    Icon: ContainerOutlined,
  },
  {
    value: McpDeploymentType.API,
    labelKey: "mcpTools.deploymentType.api",
    Icon: ApiOutlined,
  },
  {
    value: McpDeploymentType.LOCAL_IMAGE,
    labelKey: "mcpTools.deploymentType.localImage",
    Icon: CloudOutlined,
  },
] as const;

export default function McpServiceDetailModal({
  selectedService,
  onClose,
}: McpServiceDetailModalProps) {
  const { modal } = App.useApp();
  const { t } = useTranslation("common");
  const rules = useMcpFormRules();
  const [form] = Form.useForm();
  const [logsOpen, setLogsOpen] = useState(false);
  const [showServerJson, setShowServerJson] = useState(false);
  const [showConfigJson, setShowConfigJson] = useState(false);
  const [publishConfirmOpen, setPublishConfirmOpen] = useState(false);
  const [deploymentType, setDeploymentType] = useState<McpDeploymentType>(
    McpDeploymentType.REMOTE_LINK
  );
  const [assignOpen, setAssignOpen] = useState(false);
  const [tagPreviewRefreshKey, setTagPreviewRefreshKey] = useState(0);
  const [tagManagementOpen, setTagManagementOpen] = useState(false);
  const { data: tagLibraries } = useTagLibraries();
  const defaultLibrary =
    tagLibraries?.find(
      (library) => library.bucket_key === "default_resource"
    ) ?? null;
  const { data: assignDefinitions, refresh: refreshAssignDefinitions } =
    useTagDefinitions(defaultLibrary?.bucket_id ?? null);
  const [containerPort, setContainerPort] = useState<number | undefined>();

  const detail = useMcpServiceDetail({ selectedService, onClose });
  const { user } = useAuthorizationContext();
  const tenantId = user?.tenantId || null;
  const { data: groupData } = useGroupList(tenantId);
  const groups = groupData?.groups || [];
  const { draft, setDraft } = detail;

  const originalDeploymentType = useMemo(
    () =>
      draft
        ? resolveDeploymentType({
            transportType: draft.transportType,
            deploymentType: draft.deploymentType,
            configJson: draft.configJson,
            serverUrl: draft.serverUrl,
            source: draft.source,
          })
        : McpDeploymentType.REMOTE_LINK,
    [draft]
  );

  useEffect(() => {
    if (!draft) return;
    const nextDeploymentType = resolveDeploymentType({
      transportType: draft.transportType,
      deploymentType: draft.deploymentType,
      configJson: draft.configJson,
      serverUrl: draft.serverUrl,
      source: draft.source,
    });
    setDeploymentType(nextDeploymentType);
    setContainerPort(draft.containerPort);
    form.setFieldsValue({
      name: draft.name,
      description: draft.description,
      version: draft.version,
      serverUrl: draft.serverUrl,
      authorizationToken: draft.authorizationToken ?? "",
      customHeaders: draft.customHeaders
        ? JSON.stringify(draft.customHeaders, null, 2)
        : "",
      openApiJson: toPrettyRegistryJson(draft.configJson),
      containerConfigJson: toPrettyRegistryJson(draft.configJson),
      containerPort: draft.containerPort,
      group_ids: draft.groupIds
        ? draft.groupIds.split(",").map(Number).filter(Boolean)
        : undefined,
      ingroup_permission: draft.ingroupPermission || "READ_ONLY",
    });
  }, [draft, form]);

  if (!selectedService || !draft) {
    return null;
  }

  const isRemoteLink = deploymentType === McpDeploymentType.REMOTE_LINK;
  const isContainer = deploymentType === McpDeploymentType.CONTAINER;
  const isApi = deploymentType === McpDeploymentType.API;
  const isLocalImage = deploymentType === McpDeploymentType.LOCAL_IMAGE;
  const isUnsupported = deploymentType !== originalDeploymentType;
  const isReadOnly = selectedService?.permission === "READ_ONLY";
  const hasRegistryJson = Boolean(draft.registryJson);
  const hasConfigJson = Boolean(draft.configJson);

  const handleSave = async () => {
    if (isUnsupported || isReadOnly) return;
    try {
      await form.validateFields();
    } catch {
      return;
    }

    const values = form.getFieldsValue();
    let parsedCustomHeaders: Record<string, string> | undefined;
    if (values.customHeaders?.trim()) {
      try {
        parsedCustomHeaders = JSON.parse(values.customHeaders.trim());
      } catch {
        modal.error({
          content: t("mcpConfig.message.invalidCustomHeadersJson"),
        });
        return;
      }
    }

    let parsedConfigJson = draft.configJson;
    if (isApi) {
      try {
        parsedConfigJson = JSON.parse(String(values.openApiJson || "").trim());
      } catch {
        modal.error({
          content: t("mcpConfig.openApiToMcp.message.invalidJson"),
        });
        return;
      }
    }
    if (isContainer) {
      try {
        parsedConfigJson = JSON.parse(
          String(values.containerConfigJson || "").trim()
        );
      } catch {
        modal.error({
          content: t("mcpTools.add.error.containerJsonInvalid"),
        });
        return;
      }
    }

    const nextDraft = {
      ...draft,
      name: values.name ?? "",
      description: values.description ?? "",
      version: values.version ?? "",
      serverUrl: values.serverUrl ?? "",
      authorizationToken: values.authorizationToken ?? "",
      customHeaders: parsedCustomHeaders,
      configJson: parsedConfigJson,
    };
    detail.setDraft(nextDraft);
    const ok = await detail.save(nextDraft);
    if (ok) onClose();
  };

  const renderAddStyleFields = () => (
    <Card size="small" style={{ marginTop: 8 }}>
      <Space direction="vertical" style={{ width: "100%" }} size="small">
        {isRemoteLink ? (
          <>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <Form.Item
                name="name"
                rules={rules.name}
                className="mb-0"
                style={{ flex: 0.8, marginBottom: 0 }}
              >
                <Input
                  placeholder={t("mcpConfig.addServer.namePlaceholder")}
                  maxLength={20}
                  autoComplete="off"
                  disabled={isReadOnly}
                />
              </Form.Item>
              <Form.Item
                name="serverUrl"
                rules={rules.httpUrl}
                className="mb-0"
                style={{ flex: 3, marginBottom: 0 }}
              >
                <Input
                  placeholder={t("mcpConfig.addServer.urlPlaceholder")}
                  autoComplete="off"
                  disabled={isReadOnly}
                />
              </Form.Item>
            </div>
            <Form.Item
              name="description"
              rules={rules.description}
              className="mb-0"
              style={{ marginBottom: 0 }}
            >
              <Input
                placeholder={t("mcpTools.detail.serviceDescription")}
                disabled={isReadOnly}
              />
            </Form.Item>
            <Form.Item
              name="customHeaders"
              className="mb-0"
              style={{ marginBottom: 0 }}
            >
              <Input.TextArea
                placeholder={t("mcpConfig.addServer.customHeadersPlaceholder")}
                rows={2}
                style={{ fontSize: 14 }}
                disabled={isReadOnly}
              />
            </Form.Item>
            <Form.Item
              name="authorizationToken"
              rules={rules.authToken}
              className="mb-0"
              style={{ marginBottom: 0 }}
            >
              <Input.Password
                placeholder={t(
                  "mcpConfig.editServer.authorizationTokenPlaceholder"
                )}
                autoComplete="new-password"
                disabled={isReadOnly}
              />
            </Form.Item>
          </>
        ) : null}
        {isContainer ? (
          <>
            <div>
              <Form.Item className="mb-0" style={{ marginBottom: 0 }}>
                <div
                  style={{
                    fontSize: 12,
                    color: "rgba(0,0,0,0.45)",
                    display: "block",
                    marginBottom: 8,
                  }}
                >
                  {t("mcpConfig.addContainer.configHint")}
                </div>
              </Form.Item>
              <Form.Item
                name="containerConfigJson"
                rules={rules.containerConfig}
                className="mb-0"
                style={{ marginBottom: 0 }}
              >
                <Input.TextArea
                  placeholder={t("mcpConfig.addContainer.configPlaceholder")}
                  rows={6}
                  style={{ fontFamily: "monospace", fontSize: 12 }}
                  disabled={isReadOnly}
                />
              </Form.Item>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ minWidth: 80 }}>
                {t("mcpConfig.addContainer.serviceName")}:
              </span>
              <Form.Item
                name="name"
                rules={rules.name}
                className="mb-0"
                style={{ flex: "0 0 150px", marginBottom: 0 }}
              >
                <Input
                  placeholder={t(
                    "mcpConfig.addContainer.serviceNamePlaceholder"
                  )}
                  style={{ width: 150 }}
                  maxLength={20}
                  disabled={isReadOnly}
                />
              </Form.Item>
              <span style={{ minWidth: 60 }}>
                {t("mcpConfig.addContainer.port")}:
              </span>
              <InputNumber
                value={containerPort}
                min={1}
                max={65535}
                style={{ width: 120 }}
                controls={false}
                disabled
              />
            </div>
            <Form.Item
              name="description"
              rules={rules.description}
              className="mb-0"
              style={{ marginBottom: 0 }}
            >
              <Input
                placeholder={t("mcpTools.detail.serviceDescription")}
                disabled={isReadOnly}
              />
            </Form.Item>
          </>
        ) : null}
        {isApi ? (
          <>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <Form.Item
                name="name"
                rules={rules.name}
                className="mb-0"
                style={{ flex: 0.8, marginBottom: 0 }}
              >
                <Input
                  placeholder={t(
                    "mcpConfig.openapiService.form.serviceNamePlaceholder"
                  )}
                  maxLength={20}
                  disabled={isReadOnly}
                />
              </Form.Item>
              <Form.Item
                name="serverUrl"
                rules={rules.httpUrl}
                className="mb-0"
                style={{ flex: 3, marginBottom: 0 }}
              >
                <Input
                  placeholder={t(
                    "mcpConfig.openapiService.form.serverUrlPlaceholder"
                  )}
                  disabled={isReadOnly}
                />
              </Form.Item>
            </div>
            <Form.Item
              name="description"
              rules={rules.description}
              className="mb-0"
              style={{ marginBottom: 0 }}
            >
              <Input
                placeholder={t("mcpTools.detail.serviceDescription")}
                disabled={isReadOnly}
              />
            </Form.Item>
            <Form.Item
              name="customHeaders"
              className="mb-0"
              style={{ marginBottom: 0 }}
            >
              <Input.TextArea
                placeholder={t("mcpConfig.addServer.customHeadersPlaceholder")}
                rows={2}
                disabled={isReadOnly}
              />
            </Form.Item>
            <Form.Item
              name="openApiJson"
              rules={rules.openApiJson}
              className="mb-0"
              style={{ marginBottom: 0 }}
            >
              <Input.TextArea
                placeholder={t("mcpConfig.openApiToMcp.jsonPlaceholder")}
                rows={6}
                disabled={isReadOnly}
              />
            </Form.Item>
            <span style={{ fontSize: 12, color: "rgba(0,0,0,0.45)" }}>
              {t("mcpConfig.openApiToMcp.form.apiJsonHint")}
            </span>
          </>
        ) : null}
        {isLocalImage ? (
          <>
            <div>
              <Form.Item className="mb-0" style={{ marginBottom: 0 }}>
                <div
                  style={{
                    fontSize: 12,
                    color: "rgba(0,0,0,0.45)",
                    display: "block",
                    marginBottom: 8,
                  }}
                >
                  {t("mcpConfig.uploadImage.fileHint")}
                </div>
              </Form.Item>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <InputNumber
                value={containerPort}
                min={1}
                max={65535}
                style={{ width: 150 }}
                controls={false}
                disabled
              />
              <Form.Item
                name="name"
                rules={rules.name}
                className="mb-0"
                style={{ flex: 1, marginBottom: 0 }}
              >
                <Input
                  placeholder={t(
                    "mcpConfig.uploadImage.serviceNamePlaceholder"
                  )}
                  disabled={isReadOnly}
                />
              </Form.Item>
            </div>
            <Form.Item
              name="description"
              rules={rules.description}
              className="mb-0"
              style={{ marginBottom: 0 }}
            >
              <Input
                placeholder={t("mcpTools.detail.serviceDescription")}
                disabled={isReadOnly}
              />
            </Form.Item>
            <Form.Item
              name="authorizationToken"
              rules={rules.authToken}
              className="mb-0"
              style={{ marginBottom: 0 }}
            >
              <Input.Password
                placeholder={t(
                  "mcpConfig.editServer.authorizationTokenPlaceholder"
                )}
                autoComplete="new-password"
                disabled={isReadOnly}
              />
            </Form.Item>
          </>
        ) : null}
      </Space>
    </Card>
  );

  return (
    <>
      <Modal
        open
        title={
          <div>
            <div className="text-xl font-semibold leading-7 text-slate-900">
              {t("mcpTools.detail.editTitle")}
            </div>
            <div className="mt-1 text-sm font-normal text-slate-500">
              {t("mcpTools.detail.editSubtitle")}
            </div>
          </div>
        }
        footer={null}
        closable
        centered
        width={MCP_ADD_SERVICE_MODAL_WIDTH_MARKETS}
        onCancel={onClose}
        wrapClassName={`${MCP_TOOLS_MODAL_WRAP_CLASS}`}
        styles={mcpToolsModalChromeStyles()}
      >
        <div className="bg-white">
          <Form
            form={form}
            layout="vertical"
            requiredMark={false}
            className="space-y-5 px-6 py-5"
          >
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700">
                {t("mcpTools.detail.addMethod")}
              </label>
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="flex items-center gap-3">
                  {(() => {
                    const opt =
                      DEPLOYMENT_OPTIONS.find(
                        (o) => o.value === originalDeploymentType
                      ) || DEPLOYMENT_OPTIONS[0];
                    const Icon = opt.Icon;
                    return (
                      <div className="flex items-center gap-2 text-sm text-slate-700">
                        <Icon className="text-lg" />
                        <span>{t(opt.labelKey)}</span>
                      </div>
                    );
                  })()}
                </div>
              </div>
            </div>

            {isUnsupported ? (
              <Alert
                type="info"
                showIcon
                message={t("mcpTools.addModal.unsupportedTitle")}
                description={t("mcpTools.detail.deploymentChangeUnsupported")}
              />
            ) : null}

            {renderAddStyleFields()}

            <div hidden>
              <div className="space-y-2">
                <Form.Item name="name" rules={rules.name} className="mb-0">
                  <Input
                    className="w-full rounded-md"
                    placeholder={t("mcpTools.detail.serviceName")}
                    disabled={isReadOnly}
                  />
                </Form.Item>
                <Form.Item
                  name="description"
                  rules={rules.description}
                  className="mb-0"
                >
                  <Input
                    className="w-full rounded-md"
                    placeholder={t("mcpTools.detail.serviceDescription")}
                    disabled={isReadOnly}
                  />
                </Form.Item>
              </div>

              {isRemoteLink ? (
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">
                    {t("mcpTools.detail.serviceConfigTitle")}
                  </label>
                  <div className="space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
                    <div>
                      <label className="mb-1 block text-sm font-normal text-slate-500">
                        {t("mcpTools.addModal.serverUrl")}
                      </label>
                      <div className="flex items-center gap-2">
                        <Form.Item
                          name="serverUrl"
                          rules={rules.httpUrl}
                          className="mb-0 flex-1"
                        >
                          <Input
                            className="w-full rounded-md"
                            placeholder={t("mcpTools.addModal.serverUrl")}
                            disabled={isReadOnly}
                          />
                        </Form.Item>
                        <label className="flex shrink-0 items-center gap-1 text-xs text-slate-400">
                          <input
                            type="checkbox"
                            className="rounded border-slate-300"
                            checked={draft.sharedFields?.["serverUrl"] ?? false}
                            disabled={isReadOnly}
                            onChange={(e) => {
                              const next = {
                                ...(draft.sharedFields || {}),
                                serverUrl: e.target.checked,
                              };
                              setDraft((prev) =>
                                prev ? { ...prev, sharedFields: next } : prev
                              );
                            }}
                          />
                          {t("mcpTools.detail.share")}
                        </label>
                      </div>
                    </div>

                    <div>
                      <label className="mb-1 block text-sm font-normal text-slate-500">
                        {t("mcpTools.addModal.bearerTokenOptional")}
                      </label>
                      <div className="flex items-center gap-2">
                        <Form.Item
                          name="authorizationToken"
                          rules={rules.authToken}
                          className="mb-0 flex-1"
                        >
                          <Input
                            className="w-full rounded-md"
                            placeholder={t(
                              "mcpTools.addModal.bearerTokenPlaceholder"
                            )}
                            disabled={isReadOnly}
                          />
                        </Form.Item>
                        <label className="flex shrink-0 items-center gap-1 text-xs text-slate-400">
                          <input
                            type="checkbox"
                            className="rounded border-slate-300"
                            checked={
                              draft.sharedFields?.["authorizationToken"] ??
                              false
                            }
                            disabled={isReadOnly}
                            onChange={(e) => {
                              const next = {
                                ...(draft.sharedFields || {}),
                                authorizationToken: e.target.checked,
                              };
                              setDraft((prev) =>
                                prev ? { ...prev, sharedFields: next } : prev
                              );
                            }}
                          />
                          {t("mcpTools.detail.share")}
                        </label>
                      </div>
                    </div>

                    <div>
                      <label className="mb-1 block text-sm font-normal text-slate-500">
                        {t("mcpTools.addModal.customHeaders")}
                      </label>
                      <div className="flex items-center gap-2">
                        <Form.Item name="customHeaders" className="mb-0 flex-1">
                          <Input.TextArea
                            rows={2}
                            className="w-full rounded-md"
                            placeholder={t(
                              "mcpTools.addModal.customHeadersPlaceholder"
                            )}
                            disabled={isReadOnly}
                          />
                        </Form.Item>
                        <label className="flex shrink-0 items-center gap-1 self-start pt-1 text-xs text-slate-400">
                          <input
                            type="checkbox"
                            className="rounded border-slate-300"
                            checked={
                              draft.sharedFields?.["customHeaders"] ?? false
                            }
                            disabled={isReadOnly}
                            onChange={(e) => {
                              const next = {
                                ...(draft.sharedFields || {}),
                                customHeaders: e.target.checked,
                              };
                              setDraft((prev) =>
                                prev ? { ...prev, sharedFields: next } : prev
                              );
                            }}
                          />
                          {t("mcpTools.detail.share")}
                        </label>
                      </div>
                    </div>
                  </div>
                </div>
              ) : null}

              {isApi ? (
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">
                    {t("mcpTools.detail.serviceConfigTitle")}
                  </label>
                  <div className="space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
                    <div>
                      <label className="mb-1 block text-sm font-normal text-slate-500">
                        {t("mcpConfig.openapiService.form.serverUrl")}
                      </label>
                      <Form.Item
                        name="serverUrl"
                        rules={rules.httpUrl}
                        className="mb-0"
                      >
                        <Input
                          className="w-full rounded-md"
                          placeholder={t(
                            "mcpConfig.openapiService.form.serverUrlPlaceholder"
                          )}
                          disabled={isReadOnly}
                        />
                      </Form.Item>
                    </div>

                    <div>
                      <label className="mb-1 block text-sm font-normal text-slate-500">
                        {t("mcpConfig.addServer.customHeaders")}
                      </label>
                      <Form.Item name="customHeaders" className="mb-0">
                        <Input.TextArea
                          rows={2}
                          className="w-full rounded-md"
                          placeholder={t(
                            "mcpConfig.addServer.customHeadersPlaceholder"
                          )}
                          disabled={isReadOnly}
                        />
                      </Form.Item>
                    </div>

                    <div>
                      <label className="mb-1 block text-sm font-normal text-slate-500">
                        {t("mcpConfig.openapiService.form.openapiJson")}
                      </label>
                      <Form.Item name="openApiJson" className="mb-0">
                        <Input.TextArea
                          rows={6}
                          className="w-full rounded-md"
                          placeholder={t(
                            "mcpConfig.openApiToMcp.jsonPlaceholder"
                          )}
                          disabled={isReadOnly}
                        />
                      </Form.Item>
                    </div>
                  </div>
                </div>
              ) : null}

              {isContainer ? (
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">
                    {t("mcpTools.detail.serviceConfigTitle")}
                  </label>
                  <div className="space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
                    <div>
                      <label className="mb-1 block text-sm font-normal text-slate-500">
                        {t("mcpTools.addModal.containerConfig")}
                      </label>
                      <div className="flex items-center gap-2">
                        <Form.Item
                          name="containerConfigJson"
                          className="mb-0 flex-1"
                        >
                          <Input.TextArea
                            rows={5}
                            className="w-full rounded-md bg-white text-slate-600"
                            placeholder={t(
                              "mcpTools.addModal.containerConfigPlaceholder"
                            )}
                            disabled={isReadOnly}
                          />
                        </Form.Item>
                        <label className="flex shrink-0 items-center gap-1 self-start pt-1 text-xs text-slate-400">
                          <input
                            type="checkbox"
                            className="rounded border-slate-300"
                            checked={
                              draft.sharedFields?.["containerConfigJson"] ??
                              false
                            }
                            disabled={isReadOnly}
                            onChange={(e) => {
                              const next = {
                                ...(draft.sharedFields || {}),
                                containerConfigJson: e.target.checked,
                              };
                              setDraft((prev) =>
                                prev ? { ...prev, sharedFields: next } : prev
                              );
                            }}
                          />
                          {t("mcpTools.detail.share")}
                        </label>
                      </div>
                    </div>

                    <Form.Item name="containerPort" className="mb-0">
                      <ContainerPortField
                        scope="detail"
                        enabled={false}
                        containerPort={containerPort}
                        setContainerPort={(value) => {
                          setContainerPort(value);
                          form.setFieldValue("containerPort", value);
                        }}
                      />
                    </Form.Item>
                  </div>
                </div>
              ) : null}

              {isLocalImage ? (
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">
                    {t("mcpTools.detail.serviceConfigTitle")}
                  </label>
                  <div className="space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
                    <Form.Item name="containerPort" className="mb-0">
                      <ContainerPortField
                        scope="detail"
                        enabled={false}
                        containerPort={containerPort}
                        setContainerPort={(value) => {
                          setContainerPort(value);
                          form.setFieldValue("containerPort", value);
                        }}
                      />
                    </Form.Item>
                  </div>
                </div>
              ) : null}
            </div>

            <Can permission="group:read">
              <div className="mt-8 grid grid-cols-2 gap-4">
                <Form.Item
                  name="group_ids"
                  label={t("tenantResources.knowledgeBase.groupNames")}
                  className="mb-0"
                  help={
                    isApi ? (
                      <span style={{ fontSize: 12, color: "rgba(0,0,0,0.45)" }}>
                        {t("mcpTools.detail.groupPermissionUnsupported")}
                      </span>
                    ) : undefined
                  }
                >
                  <Select
                    mode="multiple"
                    showSearch={{ optionFilterProp: "label" }}
                    placeholder={t("tenantResources.knowledgeBase.groupNames")}
                    disabled={isReadOnly || isApi}
                    value={
                      draft.groupIds
                        ? draft.groupIds.split(",").map(Number)
                        : []
                    }
                    options={groups.map(
                      (g: { group_id: number; group_name: string }) => ({
                        label: g.group_name,
                        value: g.group_id,
                      })
                    )}
                    notFoundContent={
                      t("knowledgeBase.create.permission.groupPlaceholder") ||
                      t("mcpTools.detail.noGroups")
                    }
                    onChange={(values: number[]) => {
                      const next = values.join(",");
                      setDraft((prev) =>
                        prev ? { ...prev, groupIds: next } : prev
                      );
                      form.setFieldValue("group_ids", values);
                    }}
                    className="rounded-md"
                  />
                </Form.Item>
                <Can permission="kb.groups:read">
                  <Form.Item
                    name="ingroup_permission"
                    label={t("tenantResources.knowledgeBase.permission")}
                    className="mb-0"
                  >
                    <Select
                      value={draft.ingroupPermission ?? "READ_ONLY"}
                      disabled={isReadOnly || isApi}
                      onChange={(value) => {
                        setDraft((prev) =>
                          prev
                            ? {
                                ...prev,
                                ingroupPermission: value as
                                  | "EDIT"
                                  | "READ_ONLY"
                                  | "PRIVATE",
                              }
                            : prev
                        );
                        form.setFieldValue("ingroup_permission", value);
                      }}
                      options={[
                        {
                          value: "READ_ONLY",
                          label: t(
                            "knowledgeBase.ingroup.permission.READ_ONLY"
                          ),
                        },
                        {
                          value: "EDIT",
                          label: t("knowledgeBase.ingroup.permission.EDIT"),
                        },
                        {
                          value: "PRIVATE",
                          label: t("knowledgeBase.ingroup.permission.PRIVATE"),
                        },
                      ]}
                    />
                  </Form.Item>
                </Can>
              </div>
            </Can>
            <Form.Item label={t("mcpTools.detail.tags")} className="mb-2">
              <div className="flex min-w-0 items-center gap-2">
                <div className="min-w-0 flex-1 overflow-hidden whitespace-nowrap">
                  <ResourceTagChips
                    resourceType="mcp_service"
                    resourceId={String(selectedService.mcpId)}
                    max={4}
                    refreshKey={tagPreviewRefreshKey}
                    singleLine
                    emptyText={
                      <span className="text-sm text-slate-400">—</span>
                    }
                  />
                </div>
                <Button
                  type="link"
                  size="small"
                  disabled={isReadOnly}
                  onClick={() => setAssignOpen(true)}
                >
                  {t("tagManagement.action.editTags")}
                </Button>
              </div>
            </Form.Item>
          </Form>

          <div className="flex flex-col gap-y-3 border-t border-slate-100 bg-white px-6 py-4">
            <div className="flex flex-wrap gap-2">
              {isContainer || isLocalImage ? (
                <Button
                  disabled={!draft.containerId}
                  onClick={() => setLogsOpen(true)}
                >
                  {t("mcpTools.detail.viewContainerLogs")}
                </Button>
              ) : null}
              {hasRegistryJson ? (
                <Button onClick={() => setShowServerJson(true)}>
                  {t("mcpTools.registry.viewServerJson")}
                </Button>
              ) : null}
              {hasConfigJson ? (
                <Button onClick={() => setShowConfigJson(true)}>
                  {t("mcpTools.detail.viewConfigJson")}
                </Button>
              ) : null}
              <Button
                loading={detail.loadingTools}
                onClick={detail.refreshTools}
              >
                {t("mcpTools.detail.viewTools")}
              </Button>
            </div>

            <div className="flex items-center justify-end gap-3">
              <Button onClick={onClose}>{t("common.cancel")}</Button>
              <Button
                type="primary"
                loading={detail.saving}
                disabled={isUnsupported || isReadOnly}
                onClick={handleSave}
              >
                {isReadOnly
                  ? t("mcpTools.detail.noEditPermission")
                  : t("mcpTools.detail.save")}
              </Button>
            </div>
          </div>
        </div>
      </Modal>

      <McpToolListModal
        open={detail.toolsState.visible}
        onCancel={detail.closeToolsModal}
        loading={detail.loadingTools}
        tools={detail.toolsState.tools}
        serverName={draft.name || String(t("mcpTools.service.defaultName"))}
      />

      <JsonPreviewModal
        open={showServerJson && hasRegistryJson}
        title={t("mcpTools.registry.serverJsonTitle", { name: draft.name })}
        json={toPrettyRegistryJson(draft.registryJson)}
        onCancel={() => setShowServerJson(false)}
      />

      <JsonPreviewModal
        open={showConfigJson && hasConfigJson}
        title={t("mcpTools.detail.configJsonTitle", { name: draft.name })}
        json={toPrettyRegistryJson(draft.configJson)}
        onCancel={() => setShowConfigJson(false)}
      />

      {draft.containerId ? (
        <McpContainerLogsModal
          open={logsOpen}
          onCancel={() => setLogsOpen(false)}
          containerId={draft.containerId}
        />
      ) : null}

      <ResourceTagAssignmentModal
        open={assignOpen}
        onClose={() => {
          setAssignOpen(false);
          setTagPreviewRefreshKey((current) => current + 1);
        }}
        resourceType="mcp_service"
        resourceId={String(selectedService.mcpId)}
        definitions={assignDefinitions ?? []}
        canEdit={!isReadOnly}
        onManageDefinitions={() => setTagManagementOpen(true)}
      />

      <TagDefinitionManagementModal
        open={tagManagementOpen}
        onClose={() => {
          setTagManagementOpen(false);
          void refreshAssignDefinitions();
        }}
        bucketId={defaultLibrary?.bucket_id ?? 0}
        bucketName={defaultLibrary?.bucket_name ?? ""}
        canManage={!isReadOnly}
      />

      <PublishConfirmModal
        open={publishConfirmOpen}
        source={selectedService}
        publishing={detail.publishing}
        tenantId={tenantId}
        onCancel={() => setPublishConfirmOpen(false)}
        onConfirm={async (override) => {
          const ok = await detail.publish(override);
          if (ok) setPublishConfirmOpen(false);
        }}
      />
    </>
  );
}
