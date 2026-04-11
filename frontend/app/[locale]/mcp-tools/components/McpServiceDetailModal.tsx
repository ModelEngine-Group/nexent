import { Modal, Input, Button, Form, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { useEffect, useState } from "react";
import {
  MCP_CONTAINER_STATUS,
  MCP_HEALTH_STATUS,
  MCP_TRANSPORT_TYPE,
  MCP_SERVICE_STATUS,
  MCP_TAB,
} from "@/const/mcpTools";
import {
  type McpContainerStatus,
  type McpHealthStatus,
  type McpServiceItem,
} from "@/types/mcpTools";
import { extractRegistryLinks, toPrettyRegistryJson } from "@/lib/mcpTools";
import McpDescriptionField from "./McpDescriptionField";
import McpServiceDetailToolListModal from "./McpServiceDetailToolListModal";
import McpContainerLogsModal from "@/components/mcp/McpContainerLogsModal";

interface McpServiceDetailModalProps {
  open: boolean;
  selectedService: McpServiceItem | null;
  draftService: McpServiceItem | null;
  tagDrafts: string[];
  tagInputValue: string;
  healthCheckLoading: boolean;
  healthErrorModalVisible: boolean;
  healthErrorModalTitle: string;
  healthErrorModalDetail: string;
  loadingTools: boolean;
  toolsModalVisible: boolean;
  currentServerTools: any[];
  publishLoading?: boolean;
  toggleLoading?: boolean;
  setDraftService: (service: McpServiceItem) => void;
  setTagInputValue: (value: string) => void;
  addDetailTag: () => void;
  removeTag: (index: number) => void;
  handleHealthCheck: () => void;
  handleViewTools: () => void;
  handleSaveUpdates: () => void;
  closeToolsModal: () => void;
  handleRefreshTools: () => void;
  closeHealthErrorModal: () => void;
  onDeleteConfirm: (serviceName: string) => void;
  onPublishToCommunity: () => void;
  onToggleEnable: (service: McpServiceItem) => void;
  onClose: () => void;
}

export default function McpServiceDetailModal({
  open,
  selectedService,
  draftService,
  tagDrafts,
  tagInputValue,
  healthCheckLoading,
  healthErrorModalVisible,
  healthErrorModalTitle,
  healthErrorModalDetail,
  loadingTools,
  toolsModalVisible,
  currentServerTools,
  publishLoading = false,
  toggleLoading = false,
  setDraftService,
  setTagInputValue,
  addDetailTag,
  removeTag,
  handleHealthCheck,
  handleViewTools,
  handleSaveUpdates,
  closeToolsModal,
  handleRefreshTools,
  closeHealthErrorModal,
  onDeleteConfirm,
  onPublishToCommunity,
  onToggleEnable,
  onClose,
}: McpServiceDetailModalProps) {
  const [form] = Form.useForm();

  const { t } = useTranslation("common");
  const [logsModalOpen, setLogsModalOpen] = useState(false);
  const [showServerJsonModal, setShowServerJsonModal] = useState(false);
  const hasRegistryJson = Boolean(draftService?.registryJson);
  const [showConfigJsonModal, setShowConfigJsonModal] = useState(false);
  const hasConfigJson = Boolean(draftService?.configJson);

  const { websiteUrl: registryWebsiteUrl, repositoryUrl: registryRepositoryUrl } = extractRegistryLinks(
    draftService?.registryJson
  );
  const registryJsonPretty = toPrettyRegistryJson(draftService?.registryJson);
  const configJsonPretty = toPrettyRegistryJson(draftService?.configJson);

  const isHttpUrl = (value: string): boolean => {
    try {
      const parsed = new URL(value);
      return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch {
      return false;
    }
  };

  useEffect(() => {
    if (!open || !draftService) return;
    form.setFieldsValue({
      name: draftService.name,
      description: draftService.description,
      serverUrl: draftService.serverUrl,
      authorizationToken: draftService.authorizationToken ?? "",
    });
  }, [draftService, form, open]);

  const getHealthStatusLabel = (status: McpHealthStatus) => {
    if (status === MCP_HEALTH_STATUS.HEALTHY) {
      return t("mcpTools.health.healthy");
    }
    if (status === MCP_HEALTH_STATUS.UNHEALTHY) {
      return t("mcpTools.health.unhealthy");
    }
    return t("mcpTools.health.unchecked");
  };

  const getContainerStatusLabel = (status?: McpContainerStatus) => {
    if (status === MCP_CONTAINER_STATUS.RUNNING) {
      return t("mcpTools.containerStatus.running");
    }
    if (status === MCP_CONTAINER_STATUS.STOPPED) {
      return t("mcpTools.containerStatus.stopped");
    }
    return t("mcpTools.containerStatus.unknown");
  };

  if (!open || !selectedService || !draftService) {
    return null;
  }

  return (
    <>
      <Modal
        open
        footer={null}
        closable
        centered
        width={900}
        onCancel={onClose}
        styles={{
          mask: { background: "rgba(15,23,42,0.6)", backdropFilter: "blur(2px)" },
          body: { padding: 0 },
        }}
      >
        <div>
        <div className="border-b border-slate-100 px-6 py-5">
          <div>
            <h2 className="text-2xl font-semibold text-slate-900">{t("mcpTools.detail.title")}</h2>
          </div>
        </div>

        <div className="px-6 py-5 space-y-5">
          <Form form={form} layout="vertical" requiredMark={false} className="grid gap-4">
            <Form.Item
              label={t("mcpTools.detail.name")}
              name="name"
              className="mb-0 text-sm text-slate-500"
              rules={[
                { required: true, whitespace: true, message: t("mcpTools.add.validate.nameRequired") },
                { type: "string", max: 100, message: t("mcpTools.add.validate.nameMaxLength") },
              ]}
            >
              <Input
                value={draftService.name}
                onChange={(event) => {
                  setDraftService({
                    ...draftService,
                    name: event.target.value,
                  });
                  form.setFieldValue("name", event.target.value);
                }}
                className="mt-2 w-full rounded-2xl"
              />
            </Form.Item>

            <Form.Item
              label={t("mcpTools.detail.description")}
              name="description"
              className="mb-0"
              rules={[{ type: "string", max: 5000, message: t("mcpTools.add.validate.descriptionMaxLength") }]}
            >
              <McpDescriptionField
                label={t("mcpTools.detail.description")}
                value={draftService.description}
                onChange={(value) => {
                  setDraftService({ ...draftService, description: value });
                  form.setFieldValue("description", value);
                }}
                t={(key, params) => String(t(key, params as any))}
                minRows={1}
                maxRows={24}
                toggleMinChars={160}
                toggleMinLines={1}
              />
            </Form.Item>

            <Form.Item
              label={t("mcpTools.detail.serverUrl")}
              name="serverUrl"
              className="mb-0 text-sm text-slate-500"
              rules={[
                {
                  validator: async (_rule, value) => {
                    const text = String(value || "").trim();
                    if (!text) {
                      throw new Error(t("mcpTools.add.validate.httpUrlRequired"));
                    }
                    if (text.length > 500) {
                      throw new Error(t("mcpTools.add.validate.httpUrlMaxLength"));
                    }
                    if (!isHttpUrl(text)) {
                      throw new Error(t("mcpTools.add.validate.httpUrlFormat"));
                    }
                  },
                },
              ]}
            >
              <Input
                value={draftService.serverUrl}
                onChange={(event) => {
                  setDraftService({
                    ...draftService,
                    serverUrl: event.target.value,
                  });
                  form.setFieldValue("serverUrl", event.target.value);
                }}
                className="mt-2 w-full rounded-2xl"
              />
            </Form.Item>
            {draftService.transportType === MCP_TRANSPORT_TYPE.HTTP || draftService.transportType === MCP_TRANSPORT_TYPE.SSE ? (
              <Form.Item
                label={t("mcpTools.detail.bearerTokenOptional")}
                name="authorizationToken"
                className="mb-0 text-sm text-slate-500"
                rules={[{ type: "string", max: 500, message: t("mcpTools.add.validate.authorizationTokenMaxLength") }]}
              >
                <Input
                  value={draftService.authorizationToken ?? ""}
                  onChange={(event) => {
                    setDraftService({
                      ...draftService,
                      authorizationToken: event.target.value,
                    });
                    form.setFieldValue("authorizationToken", event.target.value);
                  }}
                  className="mt-2 w-full rounded-2xl"
                  placeholder={t("mcpTools.detail.bearerTokenPlaceholder")}
                />
              </Form.Item>
            ) : null}
          </Form>

          <div className="grid gap-3 text-sm text-slate-700">
            <div className="flex items-center justify-between">
              <span className="text-slate-500">{t("mcpTools.detail.source")}</span>
              <span className="font-medium text-slate-800">
                {draftService.source === MCP_TAB.LOCAL
                  ? t("mcpTools.source.local")
                  : draftService.source === MCP_TAB.COMMUNITY
                  ? t("mcpTools.source.community")
                  : t("mcpTools.source.registry")}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-500">{t("mcpTools.detail.serverType")}</span>
              <span className="font-medium text-slate-800">
                {draftService.transportType === MCP_TRANSPORT_TYPE.HTTP
                  ? t("mcpTools.serverType.http")
                  : draftService.transportType === MCP_TRANSPORT_TYPE.SSE
                  ? t("mcpTools.serverType.sse")
                  : t("mcpTools.serverType.container")}
              </span>
            </div>
            {draftService.version ? (
              <div className="flex items-center justify-between">
                <span className="text-slate-500">{t("mcpTools.detail.version")}</span>
                <span className="font-medium text-slate-800">{draftService.version}</span>
              </div>
            ) : null}
            {registryWebsiteUrl ? (
              <div className="flex items-center justify-between gap-4">
                <span className="text-slate-500">{t("mcpTools.detail.website")}</span>
                <a
                  href={registryWebsiteUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="max-w-[70%] truncate font-medium text-sky-700 hover:text-sky-800"
                >
                  {registryWebsiteUrl}
                </a>
              </div>
            ) : null}
            {registryRepositoryUrl ? (
              <div className="flex items-center justify-between gap-4">
                <span className="text-slate-500">{t("mcpTools.detail.repository")}</span>
                <a
                  href={registryRepositoryUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="max-w-[70%] truncate font-medium text-sky-700 hover:text-sky-800"
                >
                  {registryRepositoryUrl}
                </a>
              </div>
            ) : null}
            <div className="flex items-center justify-between">
              <span className="text-slate-500">{t("mcpTools.detail.status")}</span>
              <span className="font-medium text-slate-800">
                {draftService.status === MCP_SERVICE_STATUS.ENABLED
                  ? t("mcpTools.status.enabled")
                  : t("mcpTools.status.disabled")}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-500">{t("mcpTools.detail.health")}</span>
              <div className="flex items-center gap-2">
                <span className="font-medium text-slate-800">{getHealthStatusLabel(draftService.healthStatus)}</span>
                <Button
                  size="small"
                  className="rounded-full"
                  autoInsertSpace={false}
                  onClick={handleHealthCheck}
                  loading={healthCheckLoading}
                >
                  {healthCheckLoading
                    ? t("mcpTools.detail.healthChecking")
                    : t("mcpTools.detail.healthCheck")}
                </Button>
              </div>
            </div>
            {draftService.transportType === MCP_TRANSPORT_TYPE.CONTAINER ? (
              <div className="flex items-center justify-between">
                <span className="text-slate-500">{t("mcpTools.detail.containerStatus")}</span>
                <span className="font-medium text-slate-800">{getContainerStatusLabel(draftService.containerStatus)}</span>
              </div>
            ) : null}
          </div>

          <div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-slate-500">{t("mcpTools.detail.tools")}</span>
              <div className="flex items-center gap-2">
                {draftService.transportType === MCP_TRANSPORT_TYPE.CONTAINER && draftService.containerId ? (
                  <Button
                    size="small"
                    className="rounded-full"
                    autoInsertSpace={false}
                    onClick={() => setLogsModalOpen(true)}
                  >
                    {t("mcpTools.detail.viewContainerLogs")}
                  </Button>
                ) : null}
                {hasRegistryJson ? (
                  <Button
                    size="small"
                    className="rounded-full"
                    autoInsertSpace={false}
                    onClick={() => setShowServerJsonModal(true)}
                  >
                    {t("mcpTools.registry.viewServerJson")}
                  </Button>
                ) : null}
                {hasConfigJson ? (
                  <Button
                    size="small"
                    className="rounded-full"
                    autoInsertSpace={false}
                    onClick={() => setShowConfigJsonModal(true)}
                  >
                    {t("mcpTools.detail.viewConfigJson")}
                  </Button>
                ) : null}
                <Button
                  size="small"
                  className="rounded-full"
                  autoInsertSpace={false}
                  loading={loadingTools}
                  onClick={handleViewTools}
                >
                  {t("mcpTools.detail.viewTools")}
                </Button>
              </div>
            </div>
          </div>

          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{t("mcpTools.detail.tags")}</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {tagDrafts.map((tag, index) => (
                <span key={`${tag}-${index}`} className="relative inline-flex">
                  <Tag className="rounded-full px-3 py-1 m-0 leading-none">{tag}</Tag>
                  <button
                    type="button"
                    onClick={() => removeTag(index)}
                    className="absolute top-0 right-0 -translate-y-1/2 translate-x-1/2 flex h-4 w-4 items-center justify-center rounded-full bg-slate-200 text-[10px] text-slate-500 transition hover:bg-slate-300 hover:text-slate-700"
                    aria-label={t("mcpTools.detail.removeTagAria", { tag })}
                  >
                    x
                  </button>
                </span>
              ))}
              <Input
                size="small"
                value={tagInputValue}
                onChange={(event) => setTagInputValue(event.target.value)}
                onPressEnter={addDetailTag}
                onBlur={addDetailTag}
                    placeholder={t("mcpTools.detail.tagInputPlaceholder")}
                className="w-40 rounded-full"
              />
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-slate-100 px-6 py-4">
          <Button
            danger
            className="rounded-full"
            autoInsertSpace={false}
            onClick={() => onDeleteConfirm(selectedService.name)}
          >
            {t("common.delete")}
          </Button>
          <Button
            className="rounded-full"
            onClick={async () => {
              try {
                await form.validateFields();
                handleSaveUpdates();
              } catch {
                return;
              }
            }}
          >
            {t("mcpTools.detail.save")}
          </Button>
          <Button className="rounded-full" loading={publishLoading} onClick={onPublishToCommunity}>
            {t("mcpTools.community.publish")}
          </Button>
          <Button
            type="primary"
            className="rounded-full"
            autoInsertSpace={false}
            loading={toggleLoading}
            disabled={toggleLoading}
            onClick={() => onToggleEnable(selectedService)}
          >
            {draftService.status === MCP_SERVICE_STATUS.ENABLED
              ? t("mcpTools.detail.disable")
              : t("mcpTools.detail.enable")}
          </Button>
        </div>
        </div>
      </Modal>

      <McpServiceDetailToolListModal
        open={toolsModalVisible}
        onCancel={closeToolsModal}
        loading={loadingTools}
        tools={currentServerTools}
        serverName={draftService.name || String(t("mcpTools.service.defaultName"))}
        onRefresh={handleRefreshTools}
      />

      <Modal
        open={healthErrorModalVisible}
        title={healthErrorModalTitle}
        onCancel={closeHealthErrorModal}
        onOk={closeHealthErrorModal}
        okText={t("common.confirm")}
        cancelButtonProps={{ style: { display: "none" } }}
      >
        <pre className="max-h-[40vh] overflow-auto whitespace-pre-wrap break-all rounded-xl bg-slate-50 p-3 text-xs text-slate-700">
          {healthErrorModalDetail}
        </pre>
      </Modal>

      {showServerJsonModal && hasRegistryJson ? (
        <Modal
          open
          footer={null}
          closable
          centered
          width={960}
          onCancel={() => setShowServerJsonModal(false)}
          title={t("mcpTools.registry.serverJsonTitle", { name: draftService.name })}
        >
          <pre className="max-h-[65vh] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs text-slate-100">
            {registryJsonPretty}
          </pre>
        </Modal>
      ) : null}

      {showConfigJsonModal && hasConfigJson ? (
        <Modal
          open
          footer={null}
          closable
          centered
          width={960}
          onCancel={() => setShowConfigJsonModal(false)}
          title={t("mcpTools.detail.configJsonTitle", { name: draftService.name })}
        >
          <pre className="max-h-[65vh] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs text-slate-100">
            {configJsonPretty}
          </pre>
        </Modal>
      ) : null}

      {draftService.transportType === MCP_TRANSPORT_TYPE.CONTAINER && draftService.containerId ? (
        <McpContainerLogsModal
          open={logsModalOpen}
          onCancel={() => setLogsModalOpen(false)}
          containerId={draftService.containerId}
        />
      ) : null}
    </>
  );
}
