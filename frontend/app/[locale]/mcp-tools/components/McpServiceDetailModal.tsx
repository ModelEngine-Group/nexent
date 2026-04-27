import { useEffect, useState } from "react";
import { App, Modal, Input, Button, Form } from "antd";
import { useTranslation } from "react-i18next";
import {
  MCP_HEALTH_STATUS,
  MCP_SERVICE_STATUS,
  MCP_TRANSPORT_TYPE,
} from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";
import {
  extractRegistryLinks,
  getContainerStatusKey,
  getHealthStatusKey,
  getSourceLabelKey,
  getTransportLabelKey,
  toPrettyRegistryJson,
} from "@/lib/mcpTools";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import { useMcpServiceDetail } from "@/hooks/mcpTools/useMcpServiceDetail";
import McpContainerLogsModal from "@/components/mcp/McpContainerLogsModal";
import McpToolListModal from "@/components/mcp/McpToolListModal";
import TagEditor from "./shared/TagEditor";
import PublishConfirmModal from "./PublishConfirmModal";
import StatusBadge from "./shared/StatusBadge";

interface McpServiceDetailModalProps {
  selectedService: McpServiceItem | null;
  onClose: () => void;
  onToggleEnable: (service: McpServiceItem) => void;
  isToggleLoading: (mcpId?: number) => boolean;
}

export default function McpServiceDetailModal({
  selectedService,
  onClose,
  onToggleEnable,
  isToggleLoading,
}: McpServiceDetailModalProps) {
  const { modal } = App.useApp();
  const { t } = useTranslation("common");
  const rules = useMcpFormRules();
  const [form] = Form.useForm();
  const [logsOpen, setLogsOpen] = useState(false);
  const [showServerJson, setShowServerJson] = useState(false);
  const [showConfigJson, setShowConfigJson] = useState(false);
  const [publishConfirmOpen, setPublishConfirmOpen] = useState(false);

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
    draft.transportType !== MCP_TRANSPORT_TYPE.CONTAINER;

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
                rules={rules.name}
              >
                <Input
                  value={draft.name}
                  onChange={(event) => {
                    detail.setDraft({ ...draft, name: event.target.value });
                    form.setFieldValue("name", event.target.value);
                  }}
                  className="mt-2 w-full rounded-md"
                />
              </Form.Item>

              <Form.Item
                label={t("mcpTools.detail.description")}
                name="description"
                className="mb-0"
                rules={rules.description}
              >
                <Input.TextArea
                  value={draft.description}
                  onChange={(event) => {
                    detail.setDraft({
                      ...draft,
                      description: event.target.value,
                    });
                    form.setFieldValue("description", event.target.value);
                  }}
                  autoSize={{ minRows: 1, maxRows: 24 }}
                  className="mt-2 w-full rounded-md"
                />
              </Form.Item>

              <Form.Item
                label={t("mcpTools.detail.serverUrl")}
                name="serverUrl"
                className="mb-0 text-sm text-slate-500"
                rules={rules.httpUrl}
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
                  className="mt-2 w-full rounded-md"
                />
              </Form.Item>

              {isHttpLike ? (
                <Form.Item
                  label={t("mcpTools.detail.bearerTokenOptional")}
                  name="authorizationToken"
                  className="mb-0 text-sm text-slate-500"
                  rules={rules.authToken}
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
                    className="mt-2 w-full rounded-md"
                    placeholder={t("mcpTools.detail.bearerTokenPlaceholder")}
                  />
                </Form.Item>
              ) : null}
            </Form>

            <div className="grid gap-3 text-sm text-slate-700">
              <DetailRow
                label={t("mcpTools.detail.source")}
                value={t(getSourceLabelKey(draft.source))}
              />
              <DetailRow
                label={t("mcpTools.detail.serverType")}
                value={t(getTransportLabelKey(draft.transportType))}
              />
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
              <div className="flex items-center justify-between gap-3">
                <span className="shrink-0 text-slate-500">
                  {t("mcpTools.detail.status")}
                </span>
                <StatusBadge status={draft.status} />
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="shrink-0 text-slate-500">
                  {t("mcpTools.detail.health")}
                </span>
                <div className="flex min-w-0 flex-1 items-center justify-end gap-2">
                  <span className="flex items-center gap-2 font-medium text-slate-800">
                    <StatusLamp
                      variant={healthLampVariant(draft.healthStatus)}
                    />
                    {t(getHealthStatusKey(draft.healthStatus))}
                  </span>
                  <Button
                    size="small"
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
                  value={t(getContainerStatusKey(draft.containerStatus))}
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
                    autoInsertSpace={false}
                    onClick={() => setLogsOpen(true)}
                  >
                    {t("mcpTools.detail.viewContainerLogs")}
                  </Button>
                ) : null}
                {hasRegistryJson ? (
                  <Button
                    size="small"
                    autoInsertSpace={false}
                    onClick={() => setShowServerJson(true)}
                  >
                    {t("mcpTools.registry.viewServerJson")}
                  </Button>
                ) : null}
                {hasConfigJson ? (
                  <Button
                    size="small"
                    autoInsertSpace={false}
                    onClick={() => setShowConfigJson(true)}
                  >
                    {t("mcpTools.detail.viewConfigJson")}
                  </Button>
                ) : null}
                <Button
                  size="small"
                  autoInsertSpace={false}
                  loading={detail.loadingTools}
                  onClick={detail.loadTools}
                >
                  {t("mcpTools.detail.viewTools")}
                </Button>
              </div>
            </div>

            <TagEditor
              title={t("mcpTools.detail.tags")}
              tags={draft.tags}
              onAddTag={(tag) => detail.addTag(tag || "")}
              onRemoveTag={detail.removeTag}
              removeAriaKey="mcpTools.detail.removeTagAria"
              placeholderKey="mcpTools.detail.tagInputPlaceholder"
            />
          </div>

          <div className="flex items-center justify-end gap-3 border-t border-slate-100 px-6 py-4">
            <Button
              danger
              autoInsertSpace={false}
              loading={detail.deleting}
              onClick={handleDeleteClick}
            >
              {t("common.delete")}
            </Button>
            <Button loading={detail.saving} onClick={handleSave}>
              {t("mcpTools.detail.save")}
            </Button>
            <Button
              loading={detail.publishing}
              onClick={() => setPublishConfirmOpen(true)}
            >
              {t("mcpTools.community.publish")}
            </Button>
            <Button
              type="primary"
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

      {showServerJson && hasRegistryJson ? (
        <Modal
          open
          footer={null}
          closable
          centered
          width={960}
          onCancel={() => setShowServerJson(false)}
          title={t("mcpTools.registry.serverJsonTitle", { name: draft.name })}
          styles={{ body: { paddingTop: 8 } }}
        >
          <div className="rounded-md border border-slate-200 bg-slate-50">
            <pre className="max-h-[65vh] overflow-auto p-4 font-mono text-xs leading-relaxed text-slate-800">
              {toPrettyRegistryJson(draft.registryJson)}
            </pre>
          </div>
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
          styles={{ body: { paddingTop: 8 } }}
        >
          <div className="rounded-md border border-slate-200 bg-slate-50">
            <pre className="max-h-[65vh] overflow-auto p-4 font-mono text-xs leading-relaxed text-slate-800">
              {toPrettyRegistryJson(draft.configJson)}
            </pre>
          </div>
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

      <PublishConfirmModal
        open={publishConfirmOpen}
        source={selectedService}
        publishing={detail.publishing}
        onCancel={() => setPublishConfirmOpen(false)}
        onConfirm={async (override) => {
          const ok = await detail.publish(override);
          if (ok) setPublishConfirmOpen(false);
        }}
      />
    </>
  );
}

type StatusLampVariant = "success" | "neutral" | "danger";

/** Green / grey / red dot for run-state and health at a glance. */
function StatusLamp({ variant }: { variant: StatusLampVariant }) {
  const cls =
    variant === "success"
      ? "bg-emerald-500 shadow-[0_0_0_1px_rgba(16,185,129,0.35),0_0_8px_rgba(16,185,129,0.25)]"
      : variant === "danger"
        ? "bg-rose-500 shadow-[0_0_0_1px_rgba(244,63,94,0.35),0_0_8px_rgba(244,63,94,0.2)]"
        : "bg-slate-300";
  return (
    <span
      className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${cls}`}
      aria-hidden
    />
  );
}

function healthLampVariant(
  health: McpServiceItem["healthStatus"]
): StatusLampVariant {
  if (health === MCP_HEALTH_STATUS.HEALTHY) return "success";
  if (health === MCP_HEALTH_STATUS.UNHEALTHY) return "danger";
  return "neutral";
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
