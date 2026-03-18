import { Modal, Input, Button, Tag } from "antd";
import { useTranslation } from "react-i18next";
import {
  MCP_CONTAINER_STATUS,
  MCP_HEALTH_STATUS,
  MCP_SERVER_TYPE,
  MCP_SERVICE_STATUS,
  MCP_TAB,
} from "@/const/mcpTools";
import {
  type McpContainerStatus,
  type McpServiceDetailActions,
  type McpServiceDetailState,
  type McpHealthStatus,
  type McpServiceItem,
  type McpServerType,
  type McpServiceStatus,
  type McpTab,
} from "@/types/mcpTools";
import McpServiceDetailToolListModal from "./McpServiceDetailToolListModal";

interface McpServiceDetailModalProps {
  open: boolean;
  detailState: McpServiceDetailState;
  detailActions: McpServiceDetailActions;
  onDeleteConfirm: (serviceName: string) => void;
  onToggleEnable: (service: McpServiceItem) => void;
  onClose: () => void;
}

export default function McpServiceDetailModal({
  open,
  detailState,
  detailActions,
  onDeleteConfirm,
  onToggleEnable,
  onClose,
}: McpServiceDetailModalProps) {
  const {
    selectedService,
    draftService,
    tagDrafts,
    tagInputValue,
    healthCheckLoading,
    loadingTools,
    toolsModalVisible,
    currentServerTools,
  } = detailState;
  const {
    onDraftServiceChange,
    onTagInputChange,
    onAddDetailTag,
    onRemoveTag,
    onHealthCheck,
    onViewTools,
    onSaveUpdates,
    onCloseToolsModal,
    onRefreshTools,
  } = detailActions;
  const { t } = useTranslation("common");

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
        maskClosable={false}
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
          <div className="grid gap-4">
            <label className="text-sm text-slate-500">
              {t("mcpTools.detail.name")}
              <Input
                value={draftService.name}
                onChange={(event) =>
                  onDraftServiceChange({
                    ...draftService,
                    name: event.target.value,
                  })
                }
                className="mt-2 w-full rounded-2xl"
              />
            </label>
            <label className="text-sm text-slate-500">
              {t("mcpTools.detail.description")}
              <Input
                value={draftService.description}
                onChange={(event) =>
                  onDraftServiceChange({
                    ...draftService,
                    description: event.target.value,
                  })
                }
                className="mt-2 w-full rounded-2xl"
              />
            </label>
            <label className="text-sm text-slate-500">
              {t("mcpTools.detail.serverUrl")}
              <Input
                value={draftService.serverUrl}
                onChange={(event) =>
                  onDraftServiceChange({
                    ...draftService,
                    serverUrl: event.target.value,
                  })
                }
                className="mt-2 w-full rounded-2xl"
              />
            </label>
            {draftService.serverType === MCP_SERVER_TYPE.HTTP || draftService.serverType === MCP_SERVER_TYPE.SSE ? (
              <label className="text-sm text-slate-500">
                {t("mcpTools.detail.bearerTokenOptional")}
                <Input
                  value={draftService.authorizationToken ?? ""}
                  onChange={(event) =>
                    onDraftServiceChange({
                      ...draftService,
                      authorizationToken: event.target.value,
                    })
                  }
                  className="mt-2 w-full rounded-2xl"
                  placeholder={t("mcpTools.detail.bearerTokenPlaceholder")}
                />
              </label>
            ) : null}
          </div>

          <div className="grid gap-3 text-sm text-slate-700">
            <div className="flex items-center justify-between">
              <span className="text-slate-500">{t("mcpTools.detail.source")}</span>
              <span className="font-medium text-slate-800">
                {draftService.source === MCP_TAB.LOCAL ? t("mcpTools.source.local") : t("mcpTools.source.market")}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-500">{t("mcpTools.detail.serverType")}</span>
              <span className="font-medium text-slate-800">
                {draftService.serverType === MCP_SERVER_TYPE.HTTP
                  ? t("mcpTools.serverType.http")
                  : draftService.serverType === MCP_SERVER_TYPE.SSE
                  ? t("mcpTools.serverType.sse")
                  : t("mcpTools.serverType.container")}
              </span>
            </div>
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
                  onClick={onHealthCheck}
                  loading={healthCheckLoading}
                >
                  {healthCheckLoading
                    ? t("mcpTools.detail.healthChecking")
                    : t("mcpTools.detail.healthCheck")}
                </Button>
              </div>
            </div>
            {draftService.serverType === MCP_SERVER_TYPE.CONTAINER ? (
              <div className="flex items-center justify-between">
                <span className="text-slate-500">{t("mcpTools.detail.containerStatus")}</span>
                <span className="font-medium text-slate-800">{getContainerStatusLabel(draftService.containerStatus)}</span>
              </div>
            ) : null}
          </div>

          <div>
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{t("mcpTools.detail.tools")}</p>
              <Button
                size="small"
                className="rounded-full"
                autoInsertSpace={false}
                loading={loadingTools}
                onClick={onViewTools}
              >
                {t("mcpTools.detail.viewTools")}
              </Button>
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
                    onClick={() => onRemoveTag(index)}
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
                onChange={(event) => onTagInputChange(event.target.value)}
                onPressEnter={onAddDetailTag}
                onBlur={onAddDetailTag}
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
          <Button className="rounded-full" onClick={onSaveUpdates}>
            {t("mcpTools.detail.save")}
          </Button>
          <Button
            type="primary"
            className="rounded-full"
            autoInsertSpace={false}
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
        onCancel={onCloseToolsModal}
        loading={loadingTools}
        tools={currentServerTools}
        serverName={draftService.name || String(t("mcpTools.service.defaultName"))}
        onRefresh={onRefreshTools}
      />
    </>
  );
}
