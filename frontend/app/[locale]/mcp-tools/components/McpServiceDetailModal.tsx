import { useEffect, useState } from "react";
import { App, Modal, Input, Button, Form, Tag } from "antd";
import { useTranslation } from "react-i18next";
import {
  MCP_CONTAINER_STATUS,
  MCP_HEALTH_STATUS,
  MCP_TRANSPORT_TYPE,
  MCP_SERVICE_STATUS,
  MCP_TAB,
} from "@/const/mcpTools";
import type {
  McpContainerStatus,
  McpHealthStatus,
  McpServiceItem,
} from "@/types/mcpTools";
import {
  extractRegistryLinks,
  isHttpUrl,
  toPrettyRegistryJson,
} from "@/lib/mcpTools";
import { useMcpServiceDetail } from "@/hooks/mcpTools/useMcpServiceDetail";
import McpContainerLogsModal from "@/components/mcp/McpContainerLogsModal";
import McpToolListModal from "@/components/mcp/McpToolListModal";

interface McpServiceDetailModalProps {
  selectedService: McpServiceItem | null;
  onClose: () => void;
  onToggleEnable: (service: McpServiceItem) => void;
  isToggleLoading: (mcpId?: number) => boolean;
}

const resolveHealthStatusLabel = (
  status: McpHealthStatus,
  t: (key: string) => string
): string => {
  if (status === MCP_HEALTH_STATUS.HEALTHY) return t("mcpTools.health.healthy");
  if (status === MCP_HEALTH_STATUS.UNHEALTHY)
    return t("mcpTools.health.unhealthy");
  return t("mcpTools.health.unchecked");
};

const resolveContainerStatusLabel = (
  status: McpContainerStatus | undefined,
  t: (key: string) => string
): string => {
  if (status === MCP_CONTAINER_STATUS.RUNNING)
    return t("mcpTools.containerStatus.running");
  if (status === MCP_CONTAINER_STATUS.STOPPED)
    return t("mcpTools.containerStatus.stopped");
  return t("mcpTools.containerStatus.unknown");
};

const resolveSourceLabel = (
  source: McpServiceItem["source"],
  t: (key: string) => string
): string => {
  if (source === MCP_TAB.LOCAL) return t("mcpTools.source.local");
  if (source === MCP_TAB.COMMUNITY) return t("mcpTools.source.community");
  return t("mcpTools.source.registry");
};

const resolveTransportLabel = (
  transportType: McpServiceItem["transportType"],
  t: (key: string) => string
): string => {
  if (transportType === MCP_TRANSPORT_TYPE.HTTP)
    return t("mcpTools.serverType.http");
  if (transportType === MCP_TRANSPORT_TYPE.SSE)
    return t("mcpTools.serverType.sse");
  return t("mcpTools.serverType.container");
};

export default function McpServiceDetailModal({
  selectedService,
  onClose,
  onToggleEnable,
  isToggleLoading,
}: McpServiceDetailModalProps) {
  const { modal } = App.useApp();
  const { t } = useTranslation("common");
  const translate = (key: string) => String(t(key));
  const [form] = Form.useForm();
  const [logsOpen, setLogsOpen] = useState(false);
  const [showServerJson, setShowServerJson] = useState(false);
  const [showConfigJson, setShowConfigJson] = useState(false);

  const detail = useMcpServiceDetail({ selectedService, onClose });
  const { draft } = detail;

  useEffect(() => {
    if (!draft) return;
    form.setFieldsValue({
      name: draft.name,
      description: draft.description,
      serverUrl: draft.serverUrl,
      authorizationToken: draft.authorizationToken ?? "",
    });
  }, [draft, form]);

  if (!selectedService || !draft) {
    return null;
  }

  const hasRegistryJson = Boolean(draft.registryJson);
  const hasConfigJson = Boolean(draft.configJson);
  const { websiteUrl, repositoryUrl } = extractRegistryLinks(
    draft.registryJson
  );
  const isHttpLike =
    draft.transportType === MCP_TRANSPORT_TYPE.HTTP ||
    draft.transportType === MCP_TRANSPORT_TYPE.SSE;

  const handleSave = async () => {
    try {
      await form.validateFields();
    } catch {
      return;
    }
    await detail.save();
  };

  const handleDeleteClick = () => {
    modal.confirm({
      title: t("mcpTools.delete.confirmTitle"),
      content: (
        <div className="space-y-1">
          <p className="text-sm text-slate-600 break-all">
            {selectedService.name}
          </p>
          <p className="text-xs text-slate-400">
            {t("mcpTools.delete.confirmDesc")}
          </p>
        </div>
      ),
      okText: t("mcpTools.delete.confirmOk"),
      cancelText: t("mcpTools.delete.confirmCancel"),
      okButtonProps: { danger: true },
      onOk: () => detail.remove(),
    });
  };

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
          mask: {
            background: "rgba(15,23,42,0.6)",
            backdropFilter: "blur(2px)",
          },
          body: { padding: 0 },
        }}
      >
        <div>
          <div className="border-b border-slate-100 px-6 py-5">
            <h2 className="text-2xl font-semibold text-slate-900">
              {t("mcpTools.detail.title")}
            </h2>
          </div>

          <div className="px-6 py-5 space-y-5">
            <Form
              form={form}
              layout="vertical"
              requiredMark={false}
              className="grid gap-4"
            >
              <Form.Item
                label={t("mcpTools.detail.name")}
                name="name"
                className="mb-0 text-sm text-slate-500"
                rules={[
                  {
                    required: true,
                    whitespace: true,
                    message: t("mcpTools.add.validate.nameRequired"),
                  },
                  {
                    type: "string",
                    max: 100,
                    message: t("mcpTools.add.validate.nameMaxLength"),
                  },
                ]}
              >
                <Input
                  value={draft.name}
                  onChange={(event) => {
                    detail.setDraft({ ...draft, name: event.target.value });
                    form.setFieldValue("name", event.target.value);
                  }}
                  className="mt-2 w-full rounded-2xl"
                />
              </Form.Item>

              <Form.Item
                label={t("mcpTools.detail.description")}
                name="description"
                className="mb-0"
                rules={[
                  {
                    type: "string",
                    max: 5000,
                    message: t("mcpTools.add.validate.descriptionMaxLength"),
                  },
                ]}
              >
                <Input.TextArea
                  value={draft.description}
                  onChange={(event) => {
                    detail.setDraft({ ...draft, description: event.target.value });
                    form.setFieldValue("description", event.target.value);
                  }}
                  autoSize={{ minRows: 1, maxRows: 24 }}
                  className="mt-2 w-full rounded-2xl"
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
                      if (!text)
                        throw new Error(
                          t("mcpTools.add.validate.httpUrlRequired")
                        );
                      if (text.length > 500)
                        throw new Error(
                          t("mcpTools.add.validate.httpUrlMaxLength")
                        );
                      if (!isHttpUrl(text))
                        throw new Error(
                          t("mcpTools.add.validate.httpUrlFormat")
                        );
                    },
                  },
                ]}
              >
                <Input
                  value={draft.serverUrl}
                  onChange={(event) => {
                    detail.setDraft({
                      ...draft,
                      serverUrl: event.target.value,
                    });
                    form.setFieldValue("serverUrl", event.target.value);
                  }}
                  className="mt-2 w-full rounded-2xl"
                />
              </Form.Item>

              {isHttpLike ? (
                <Form.Item
                  label={t("mcpTools.detail.bearerTokenOptional")}
                  name="authorizationToken"
                  className="mb-0 text-sm text-slate-500"
                  rules={[
                    {
                      type: "string",
                      max: 500,
                      message: t(
                        "mcpTools.add.validate.authorizationTokenMaxLength"
                      ),
                    },
                  ]}
                >
                  <Input
                    value={draft.authorizationToken ?? ""}
                    onChange={(event) => {
                      detail.setDraft({
                        ...draft,
                        authorizationToken: event.target.value,
                      });
                      form.setFieldValue(
                        "authorizationToken",
                        event.target.value
                      );
                    }}
                    className="mt-2 w-full rounded-2xl"
                    placeholder={t("mcpTools.detail.bearerTokenPlaceholder")}
                  />
                </Form.Item>
              ) : null}
            </Form>

            <div className="grid gap-3 text-sm text-slate-700">
              <DetailRow
                label={t("mcpTools.detail.source")}
                value={resolveSourceLabel(draft.source, translate)}
              />
              <DetailRow
                label={t("mcpTools.detail.serverType")}
                value={resolveTransportLabel(draft.transportType, translate)}
              />
              {draft.version ? (
                <DetailRow
                  label={t("mcpTools.detail.version")}
                  value={draft.version}
                />
              ) : null}
              {websiteUrl ? (
                <DetailLink
                  label={t("mcpTools.detail.website")}
                  href={websiteUrl}
                />
              ) : null}
              {repositoryUrl ? (
                <DetailLink
                  label={t("mcpTools.detail.repository")}
                  href={repositoryUrl}
                />
              ) : null}
              <DetailRow
                label={t("mcpTools.detail.status")}
                value={
                  draft.status === MCP_SERVICE_STATUS.ENABLED
                    ? t("mcpTools.status.enabled")
                    : t("mcpTools.status.disabled")
                }
              />
              <div className="flex items-center justify-between">
                <span className="text-slate-500">
                  {t("mcpTools.detail.health")}
                </span>
                <div className="flex items-center gap-2">
                  <span className="font-medium text-slate-800">
                    {resolveHealthStatusLabel(draft.healthStatus, translate)}
                  </span>
                  <Button
                    size="small"
                    className="rounded-full"
                    autoInsertSpace={false}
                    onClick={detail.runHealthCheck}
                    loading={detail.healthChecking}
                  >
                    {detail.healthChecking
                      ? t("mcpTools.detail.healthChecking")
                      : t("mcpTools.detail.healthCheck")}
                  </Button>
                </div>
              </div>
              {draft.transportType === MCP_TRANSPORT_TYPE.CONTAINER ? (
                <DetailRow
                  label={t("mcpTools.detail.containerStatus")}
                  value={resolveContainerStatusLabel(
                    draft.containerStatus,
                    translate
                  )}
                />
              ) : null}
            </div>

            <div className="flex items-center justify-between gap-3">
              <span className="text-slate-500 text-sm">
                {t("mcpTools.detail.tools")}
              </span>
              <div className="flex items-center gap-2">
                {draft.transportType === MCP_TRANSPORT_TYPE.CONTAINER &&
                draft.containerId ? (
                  <Button
                    size="small"
                    className="rounded-full"
                    autoInsertSpace={false}
                    onClick={() => setLogsOpen(true)}
                  >
                    {t("mcpTools.detail.viewContainerLogs")}
                  </Button>
                ) : null}
                {hasRegistryJson ? (
                  <Button
                    size="small"
                    className="rounded-full"
                    autoInsertSpace={false}
                    onClick={() => setShowServerJson(true)}
                  >
                    {t("mcpTools.registry.viewServerJson")}
                  </Button>
                ) : null}
                {hasConfigJson ? (
                  <Button
                    size="small"
                    className="rounded-full"
                    autoInsertSpace={false}
                    onClick={() => setShowConfigJson(true)}
                  >
                    {t("mcpTools.detail.viewConfigJson")}
                  </Button>
                ) : null}
                <Button
                  size="small"
                  className="rounded-full"
                  autoInsertSpace={false}
                  loading={detail.loadingTools}
                  onClick={detail.loadTools}
                >
                  {t("mcpTools.detail.viewTools")}
                </Button>
              </div>
            </div>

            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                {t("mcpTools.detail.tags")}
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {draft.tags.map((tag, index) => (
                  <span
                    key={`${tag}-${index}`}
                    className="relative inline-flex"
                  >
                    <Tag className="rounded-full px-3 py-1 m-0 leading-none">
                      {tag}
                    </Tag>
                    <button
                      type="button"
                      onClick={() => detail.removeTag(index)}
                      className="absolute top-0 right-0 -translate-y-1/2 translate-x-1/2 flex h-4 w-4 items-center justify-center rounded-full bg-slate-200 text-[10px] text-slate-500 transition hover:bg-slate-300 hover:text-slate-700"
                      aria-label={t("mcpTools.detail.removeTagAria", { tag })}
                    >
                      x
                    </button>
                  </span>
                ))}
                <Input
                  size="small"
                  value={detail.tagInput}
                  onChange={(event) => detail.setTagInput(event.target.value)}
                  onPressEnter={detail.addTag}
                  onBlur={detail.addTag}
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
              loading={detail.deleting}
              onClick={handleDeleteClick}
            >
              {t("common.delete")}
            </Button>
            <Button
              className="rounded-full"
              loading={detail.saving}
              onClick={handleSave}
            >
              {t("mcpTools.detail.save")}
            </Button>
            <Button
              className="rounded-full"
              loading={detail.publishing}
              onClick={detail.publish}
            >
              {t("mcpTools.community.publish")}
            </Button>
            <Button
              type="primary"
              className="rounded-full"
              autoInsertSpace={false}
              loading={isToggleLoading(selectedService.mcpId)}
              disabled={isToggleLoading(selectedService.mcpId)}
              onClick={() => onToggleEnable(selectedService)}
            >
              {draft.status === MCP_SERVICE_STATUS.ENABLED
                ? t("mcpTools.detail.disable")
                : t("mcpTools.detail.enable")}
            </Button>
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

      <Modal
        open={detail.healthError.visible}
        title={detail.healthError.title}
        onCancel={detail.closeHealthError}
        onOk={detail.closeHealthError}
        okText={t("common.confirm")}
        cancelButtonProps={{ style: { display: "none" } }}
      >
        <pre className="max-h-[40vh] overflow-auto whitespace-pre-wrap break-all rounded-xl bg-slate-50 p-3 text-xs text-slate-700">
          {detail.healthError.detail}
        </pre>
      </Modal>

      {showServerJson && hasRegistryJson ? (
        <Modal
          open
          footer={null}
          closable
          centered
          width={960}
          onCancel={() => setShowServerJson(false)}
          title={t("mcpTools.registry.serverJsonTitle", { name: draft.name })}
        >
          <pre className="max-h-[65vh] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs text-slate-100">
            {toPrettyRegistryJson(draft.registryJson)}
          </pre>
        </Modal>
      ) : null}

      {showConfigJson && hasConfigJson ? (
        <Modal
          open
          footer={null}
          closable
          centered
          width={960}
          onCancel={() => setShowConfigJson(false)}
          title={t("mcpTools.detail.configJsonTitle", { name: draft.name })}
        >
          <pre className="max-h-[65vh] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs text-slate-100">
            {toPrettyRegistryJson(draft.configJson)}
          </pre>
        </Modal>
      ) : null}

      {draft.transportType === MCP_TRANSPORT_TYPE.CONTAINER &&
      draft.containerId ? (
        <McpContainerLogsModal
          open={logsOpen}
          onCancel={() => setLogsOpen(false)}
          containerId={draft.containerId}
        />
      ) : null}
    </>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-slate-500">{label}</span>
      <span className="font-medium text-slate-800">{value}</span>
    </div>
  );
}

function DetailLink({ label, href }: { label: string; href: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="text-slate-500">{label}</span>
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="max-w-[70%] truncate font-medium text-sky-700 hover:text-sky-800"
      >
        {href}
      </a>
    </div>
  );
}
