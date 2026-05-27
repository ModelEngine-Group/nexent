import { useEffect, useState } from "react";
import { App, Modal, Input, Button, Form, Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import {
  GitFork,
  Globe,
  Link,
  Package,
  Zap,
  Wrench,
  Calendar,
  Activity,
  Server,
  Tag as TagIcon,
  ExternalLink,
  Trash2,
  Upload,
  Pencil,
  Save,
  X,
  Settings,
  Play,
  Square,
  RefreshCw,
  Eye,
  FileText,
  Container,
} from "lucide-react";
import {
  McpHealthStatus,
  McpServiceStatus,
  McpTransportType,
  MCP_TOOLS_MODAL_WRAP_CLASS,
  mcpToolsModalChromeStyles,
} from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";
import TransportIcon from "./shared/TransportIcon";
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
import { useMcpServiceToggle } from "@/hooks/mcpTools/useMcpServiceToggle";
import McpContainerLogsModal from "@/components/mcp/McpContainerLogsModal";
import McpToolListModal from "@/components/mcp/McpToolListModal";
import TagEditor from "./shared/TagEditor";
import JsonPreviewModal from "./shared/JsonPreviewModal";
import PublishConfirmModal from "./PublishConfirmModal";
import StatusBadge from "./shared/StatusBadge";

interface McpServiceDetailModalProps {
  selectedService: McpServiceItem | null;
  onClose: () => void;
  onToggled?: (mcpId: number, next: McpServiceStatus) => void;
}

export default function McpServiceDetailModal({
  selectedService,
  onClose,
  onToggled: onStatusChanged,
}: McpServiceDetailModalProps) {
  const { modal } = App.useApp();
  const { t } = useTranslation("common");
  const rules = useMcpFormRules();
  const [form] = Form.useForm();
  const [logsOpen, setLogsOpen] = useState(false);
  const [showServerJson, setShowServerJson] = useState(false);
  const [showConfigJson, setShowConfigJson] = useState(false);
  const [publishConfirmOpen, setPublishConfirmOpen] = useState(false);
  const [isEditing, setIsEditing] = useState(false);

  const detail = useMcpServiceDetail({ selectedService, onClose });
  const { draft } = detail;
  const toggle = useMcpServiceToggle();

  useEffect(() => {
    if (!draft) return;
    form.setFieldsValue({
      name: draft.name,
      description: draft.description,
      serverUrl: draft.serverUrl,
      authorizationToken: draft.authorizationToken ?? "",
      customHeaders: draft.customHeaders ? JSON.stringify(draft.customHeaders, null, 2) : "",
    });
  }, [draft, form]);

  if (!selectedService || !draft) {
    return null;
  }

  const toolsRefreshing = toggle.isRefreshing(selectedService.mcpId);
  const toggleLoading = toggle.isToggling(selectedService.mcpId);
  const toggleBusy = toggleLoading || toolsRefreshing;

  const hasRegistryJson = Boolean(draft.registryJson);
  const hasConfigJson = Boolean(draft.configJson);
  const { websiteUrl, repositoryUrl } = extractRegistryLinks(
    draft.registryJson
  );
  const isHttpLike = draft.transportType !== McpTransportType.CONTAINER;

  const handleSave = async () => {
    try {
      await form.validateFields();
    } catch {
      return;
    }
    // Sync form values to draft before saving
    const values = form.getFieldsValue();
    // Parse custom headers JSON if provided
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
    detail.setDraft((prev) => prev ? {
      ...prev,
      name: values.name ?? "",
      description: values.description ?? "",
      serverUrl: values.serverUrl ?? "",
      authorizationToken: values.authorizationToken ?? "",
      customHeaders: parsedCustomHeaders,
    } : prev);
    await detail.save();
    setIsEditing(false);
  };

  const handleStartEdit = () => {
    // Ensure form has current values when entering edit mode
    form.setFieldsValue({
      name: draft.name,
      description: draft.description,
      serverUrl: draft.serverUrl,
      authorizationToken: draft.authorizationToken ?? "",
      customHeaders: draft.customHeaders ? JSON.stringify(draft.customHeaders, null, 2) : "",
    });
    setIsEditing(true);
  };

  const handleCancelEdit = () => {
    form.setFieldsValue({
      name: draft.name,
      description: draft.description,
      serverUrl: draft.serverUrl,
      authorizationToken: draft.authorizationToken ?? "",
      customHeaders: draft.customHeaders ? JSON.stringify(draft.customHeaders, null, 2) : "",
    });
    setIsEditing(false);
  };

  const handleDeleteClick = () => {
    modal.confirm({
      title: t("mcpTools.delete.confirmTitle"),
      centered: true,
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
        width={620}
        style={{ top: 20 }}
        onCancel={onClose}
        wrapClassName={`${MCP_TOOLS_MODAL_WRAP_CLASS}`}
        styles={mcpToolsModalChromeStyles()}
      >
        <Form
          form={form}
          className="bg-gradient-to-b from-slate-50 to-white"
        >
          {/* Header - Name, Description, Status and Actions */}
          <div className="border-b border-slate-200/60 bg-white px-6 py-5">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                {/* Title and Description */}
                <div className="min-h-[60px]">
                  {isEditing ? (
                    <div className="space-y-2">
                      <Form.Item name="name" className="mb-0" rules={rules.name}>
                        <Input
                          className="rounded-lg font-semibold text-lg"
                          placeholder={t("mcpTools.detail.name")}
                        />
                      </Form.Item>
                      <Form.Item name="description" className="mb-0" rules={rules.description}>
                        <Input.TextArea
                          className="rounded-lg"
                          placeholder={t("mcpTools.detail.description")}
                          autoSize={{ minRows: 1, maxRows: 3 }}
                        />
                      </Form.Item>
                    </div>
                  ) : (
                    <>
                      <div className="flex items-center gap-3">
                        <TransportIcon
                          transportType={draft.transportType}
                          label={draft.transportType}
                          className="!h-10 !w-10"
                        />
                        <div className="flex items-center gap-3 min-w-0">
                          <h2 className="text-xl font-semibold tracking-tight text-slate-900 truncate">
                            {draft.name}
                          </h2>
                          <StatusBadge status={draft.enabled} />
                        </div>
                      </div>
                      <p className="mt-1.5 text-sm text-slate-500 line-clamp-2">
                        {draft.description || t("mcpTools.detail.noDescription")}
                      </p>
                    </>
                  )}
                </div>
              </div>

              {/* Action Buttons - Edit Mode */}
              {isEditing ? (
                <div className="flex items-center gap-2 shrink-0">
                  <Button
                    onClick={handleCancelEdit}
                    icon={<X className="h-4 w-4" />}
                  >
                    {t("common.cancel")}
                  </Button>
                  <Button
                    type="primary"
                    loading={detail.saving}
                    onClick={handleSave}
                    icon={<Save className="h-4 w-4" />}
                  >
                    {t("common.save")}
                  </Button>
                </div>
              ) : (
                <div className="flex items-center gap-2 shrink-0">
                  <Button
                    onClick={handleStartEdit}
                    icon={<Pencil className="h-4 w-4" />}
                  >
                    {t("common.edit")}
                  </Button>
                </div>
              )}
            </div>

            {/* Action Buttons - Non-Edit Mode */}
            {!isEditing && (
              <div className="mt-3 -mx-6 px-6">
                <div className="flex items-center gap-2">
                  {/* Enable/Disable Button */}
                  <Button
                    type={draft.enabled === McpServiceStatus.ENABLED ? "default" : "primary"}
                    autoInsertSpace={false}
                    loading={toggleLoading}
                    disabled={toggleBusy}
                    onClick={async () => {
                      const next = await toggle.toggle(selectedService);
                      onStatusChanged?.(selectedService.mcpId as number, next);
                    }}
                    className={`flex-1 !shadow-none ${draft.enabled === McpServiceStatus.ENABLED ? "!bg-slate-100 !border-slate-200 !text-slate-700 hover:!bg-slate-200" : ""}`}
                  >
                    <span className="flex items-center justify-center gap-2">
                      {draft.enabled === McpServiceStatus.ENABLED ? (
                        <Square className="h-4 w-4" />
                      ) : (
                        <Play className="h-4 w-4" />
                      )}
                      {draft.enabled === McpServiceStatus.ENABLED
                        ? t("mcpTools.detail.disable")
                        : t("mcpTools.detail.enable")}
                    </span>
                  </Button>

                  {/* Health Check Button */}
                  <Tooltip title={detail.healthChecking ? t("mcpTools.detail.healthChecking") : t("mcpTools.detail.healthCheck")}>
                    <Button
                      onClick={detail.runHealthCheck}
                      loading={detail.healthChecking}
                      icon={<RefreshCw className={`h-4 w-4 ${detail.healthChecking ? "animate-spin" : ""}`} />}
                    />
                  </Tooltip>

                  {/* Publish and Delete Buttons */}
                  <div className="flex gap-2 shrink-0">
                    <Tooltip title={t("mcpTools.community.publish")}>
                      <Button
                        loading={detail.publishing}
                        onClick={() => setPublishConfirmOpen(true)}
                        icon={<Upload className="h-4 w-4" />}
                      />
                    </Tooltip>

                    <Tooltip title={t("common.delete")}>
                      <Button
                        danger
                        autoInsertSpace={false}
                        loading={detail.deleting}
                        onClick={handleDeleteClick}
                        icon={<Trash2 className="h-4 w-4" />}
                      />
                    </Tooltip>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Content */}
          <div className="px-6 py-5 space-y-5">
            {/* Service Status Section - First */}
            <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm">
              <h3 className="flex items-center gap-2 text-sm font-medium text-slate-700 mb-4">
                <Zap className="h-4 w-4 text-slate-400" />
                {t("mcpTools.detail.serviceStatus")}
              </h3>
              <div className="space-y-3">
                <InfoRow
                  icon={<Package className="h-3.5 w-3.5" />}
                  label={t("mcpTools.detail.source")}
                  value={t(getSourceLabelKey(draft.source))}
                />
                <InfoRow
                  icon={<GitFork className="h-3.5 w-3.5" />}
                  label={t("mcpTools.detail.serverType")}
                  value={t(getTransportLabelKey(draft.transportType))}
                />
                {draft.transportType === McpTransportType.CONTAINER ? (
                  <InfoRow
                    icon={<Server className="h-3.5 w-3.5" />}
                    label={t("mcpTools.detail.containerStatus")}
                    value={t(getContainerStatusKey(draft.containerStatus))}
                    valueClass={getContainerStatusColor(draft.containerStatus)}
                  />
                ) : null}
                <div className="flex items-center justify-between py-1.5">
                  <div className="flex items-center gap-2 text-slate-500">
                    <Activity className="h-3.5 w-3.5" />
                    <span>{t("mcpTools.detail.health")}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusLamp
                      variant={healthLampVariant(draft.healthStatus)}
                    />
                    <span className={`font-medium ${
                      draft.healthStatus === McpHealthStatus.HEALTHY
                        ? "text-emerald-600"
                        : draft.healthStatus === McpHealthStatus.UNHEALTHY
                          ? "text-rose-600"
                          : "text-slate-500"
                    }`}>
                      {t(getHealthStatusKey(draft.healthStatus))}
                    </span>
                  </div>
                </div>
              </div>

              {/* Action Buttons - removed, now in header */}
            </section>

            {/* Service Configuration Section */}
            <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm">
              <h3 className="flex items-center gap-2 text-sm font-medium text-slate-700 mb-4">
                <Settings className="h-4 w-4 text-slate-400" />
                {t("mcpTools.detail.serviceConfig")}
              </h3>
              <div className="space-y-3">
                <div>
                  <label className="block text-xs text-slate-500 mb-1.5">
                    {t("mcpTools.detail.serverUrl")}
                  </label>
                  <div className="min-h-[38px]">
                    {isEditing ? (
                      <Form.Item name="serverUrl" className="mb-0" rules={rules.httpUrl}>
                        <Input
                          className="rounded-lg"
                          placeholder="https://"
                        />
                      </Form.Item>
                    ) : (
                      <div className="text-sm text-slate-700 font-medium py-1.5 px-3 bg-slate-50 rounded-lg">
                        {draft.serverUrl || "-"}
                      </div>
                    )}
                  </div>
                </div>

                {isHttpLike && (
                  <div>
                    <label className="block text-xs text-slate-500 mb-1.5">
                      {t("mcpTools.detail.bearerTokenOptional")}
                    </label>
                    <div className="min-h-[38px]">
                      {isEditing ? (
                        <Form.Item name="authorizationToken" className="mb-0" rules={rules.authToken}>
                          <Input.Password
                            className="rounded-lg"
                            placeholder={t("mcpTools.detail.bearerTokenPlaceholder")}
                          />
                        </Form.Item>
                      ) : (
                        <div className="text-sm text-slate-700 font-medium py-1.5 px-3 bg-slate-50 rounded-lg">
                          {draft.authorizationToken ? "••••••••" : "-"}
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {isHttpLike && (
                  <div>
                    <label className="block text-xs text-slate-500 mb-1.5">
                      {t("mcpTools.addModal.customHeaders")}
                    </label>
                    <div className="min-h-[38px]">
                      {isEditing ? (
                        <Form.Item name="customHeaders" className="mb-0">
                          <Input.TextArea
                            className="rounded-lg"
                            placeholder={t("mcpTools.addModal.customHeadersPlaceholder")}
                            autoSize={{ minRows: 1, maxRows: 3 }}
                          />
                        </Form.Item>
                      ) : (
                        <div className="text-sm text-slate-700 font-medium py-1.5 px-3 bg-slate-50 rounded-lg">
                          {draft.customHeaders ? JSON.stringify(draft.customHeaders) : "-"}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </section>

            {/* Links Section */}
            {(websiteUrl || repositoryUrl) && (
              <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm">
                <h3 className="flex items-center gap-2 text-sm font-medium text-slate-700 mb-4">
                  <Link className="h-4 w-4 text-slate-400" />
                  {t("mcpTools.detail.links")}
                </h3>
                <div className="space-y-2">
                  {websiteUrl && (
                    <LinkRow
                      icon={<Globe className="h-3.5 w-3.5" />}
                      label={t("mcpTools.detail.website")}
                      href={websiteUrl}
                    />
                  )}
                  {repositoryUrl && (
                    <LinkRow
                      icon={<GitFork className="h-3.5 w-3.5" />}
                      label={t("mcpTools.detail.repository")}
                      href={repositoryUrl}
                    />
                  )}
                </div>
              </section>
            )}

            {/* Tools Section */}
            <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm">
              <h3 className="flex items-center gap-2 text-sm font-medium text-slate-700 mb-4">
                <Wrench className="h-4 w-4 text-slate-400" />
                {t("mcpTools.detail.tools")}
              </h3>
              <div className="flex flex-wrap gap-2">
                {draft.containerId && (
                  <Button
                    size="small"
                    autoInsertSpace={false}
                    onClick={() => setLogsOpen(true)}
                    icon={<FileText className="h-3.5 w-3.5" />}
                  >
                    {t("mcpTools.detail.viewContainerLogs")}
                  </Button>
                )}
                {hasRegistryJson && (
                  <Button
                    size="small"
                    autoInsertSpace={false}
                    onClick={() => setShowServerJson(true)}
                    icon={<FileText className="h-3.5 w-3.5" />}
                  >
                    {t("mcpTools.registry.viewServerJson")}
                  </Button>
                )}
                {hasConfigJson && (
                  <Button
                    size="small"
                    autoInsertSpace={false}
                    onClick={() => setShowConfigJson(true)}
                    icon={<Container className="h-3.5 w-3.5" />}
                  >
                    {t("mcpTools.detail.viewConfigJson")}
                  </Button>
                )}
                <Button
                  size="small"
                  autoInsertSpace={false}
                  loading={detail.loadingTools}
                  onClick={detail.loadTools}
                  icon={<Eye className="h-3.5 w-3.5" />}
                >
                  {t("mcpTools.detail.viewTools")}
                </Button>
              </div>
            </section>

            {/* Tags Section */}
            <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm">
              <h3 className="flex items-center gap-2 text-sm font-medium text-slate-700 mb-4">
                <TagIcon className="h-4 w-4 text-slate-400" />
                {t("mcpTools.detail.tags")}
              </h3>
              <TagEditor
                tags={draft.tags}
                onAddTag={(tag) => detail.addTag(tag || "")}
                onRemoveTag={detail.removeTag}
                removeAriaKey="mcpTools.detail.removeTagAria"
                placeholderKey="mcpTools.detail.tagInputPlaceholder"
                loading={detail.tagSaving}
              />
            </section>
          </div>
        </Form>
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
  if (health === McpHealthStatus.HEALTHY) return "success";
  if (health === McpHealthStatus.UNHEALTHY) return "danger";
  return "neutral";
}

interface InfoRowProps {
  icon: React.ReactNode;
  label: string;
  value: string;
  valueClass?: string;
}

/**
 * Displays a label with icon on the left and value on the right.
 */
function InfoRow({ icon, label, value, valueClass }: InfoRowProps) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <div className="flex items-center gap-2 text-slate-500">
        {icon}
        <span className="text-sm">{label}</span>
      </div>
      <span className={`text-sm font-medium ${valueClass || "text-slate-700"}`}>
        {value}
      </span>
    </div>
  );
}

interface LinkRowProps {
  icon: React.ReactNode;
  label: string;
  href: string;
}

/**
 * Displays a label with icon on the left and clickable link on the right.
 */
function LinkRow({ icon, label, href }: LinkRowProps) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <div className="flex items-center gap-2 text-slate-500">
        {icon}
        <span className="text-sm">{label}</span>
      </div>
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="flex items-center gap-1 text-sm font-medium text-sky-600 hover:text-sky-700"
      >
        <span className="max-w-[200px] truncate">{href.replace(/^https?:\/\//, "")}</span>
        <ExternalLink className="h-3 w-3 shrink-0" />
      </a>
    </div>
  );
}

/**
 * Returns the appropriate color class for container status display.
 */
function getContainerStatusColor(status: string | undefined): string {
  switch (status) {
    case "running":
      return "text-emerald-600";
    case "stopped":
      return "text-rose-600";
    default:
      return "text-slate-500";
  }
}
