import { useState } from "react";
import { Button, Modal } from "antd";
import { MCP_REGISTRY_SERVER_STATUS } from "@/const/mcpTools";
import {
  extractRegistryLinks,
  formatRegistryDate,
  formatRegistryVersion,
  toPrettyRegistryJson,
} from "@/lib/mcpTools";
import type { CommunityMcpCard } from "@/types/mcpTools";

interface Props {
  service: CommunityMcpCard;
  t: (key: string, params?: Record<string, unknown>) => string;
  onClose: () => void;
  onQuickAddFromCommunity: (service: CommunityMcpCard) => void;
}

export default function McpCommunityDetailModal({
  service,
  t,
  onClose,
  onQuickAddFromCommunity,
}: Props) {
  const [showServerJsonModal, setShowServerJsonModal] = useState(false);
  const [showConfigJsonModal, setShowConfigJsonModal] = useState(false);
  const { websiteUrl, repositoryUrl } = extractRegistryLinks(service.serverJson as Record<string, unknown>);
  const serverJsonPretty = toPrettyRegistryJson(service.serverJson as Record<string, unknown>);
  const configJsonPretty = toPrettyRegistryJson((service.configJson || undefined) as Record<string, unknown> | undefined);
  const hasServerJson = Boolean(service.serverJson && Object.keys(service.serverJson).length > 0);
  const hasConfigJson = Boolean(service.configJson && Object.keys(service.configJson).length > 0);
  const serverTypeText =
    service.transportType === "sse"
      ? t("mcpTools.serverType.sse")
      : service.transportType === "stdio"
      ? t("mcpTools.serverType.stdio")
      : t("mcpTools.serverType.http");
  const sourceText = t("mcpTools.source.community");

  const statusClassName =
    service.status === MCP_REGISTRY_SERVER_STATUS.ACTIVE
      ? "bg-emerald-100 text-emerald-700"
      : service.status === MCP_REGISTRY_SERVER_STATUS.DEPRECATED
      ? "bg-amber-100 text-amber-700"
      : "bg-slate-100 text-slate-600";
  const statusTextKey =
    service.status === MCP_REGISTRY_SERVER_STATUS.ACTIVE
      ? "mcpTools.community.status.active"
      : service.status === MCP_REGISTRY_SERVER_STATUS.DEPRECATED
      ? "mcpTools.community.status.deprecated"
      : "mcpTools.community.status.unknown";

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
          mask: { background: "rgba(15,23,42,0.4)" },
          body: { padding: 0 },
        }}
      >
        <div>
          <div className="border-b border-slate-100 px-6 py-5">
            <h2 className="text-2xl font-semibold text-slate-900">{t("mcpTools.detail.title")}</h2>
          </div>

          <div className="px-6 py-5 space-y-5">
            <div className="grid gap-4">
              <div>
                <p className="text-sm text-slate-500">{t("mcpTools.detail.name")}</p>
                <p className="mt-1 break-all rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-medium text-slate-800">
                  {service.name || "-"}
                </p>
              </div>
              <div>
                <p className="text-sm text-slate-500">{t("mcpTools.detail.description")}</p>
                <p className="mt-1 break-all rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-700">
                  {service.description || "-"}
                </p>
              </div>
              <div>
                <p className="text-sm text-slate-500">{t("mcpTools.detail.serverUrl")}</p>
                <p className="mt-1 break-all rounded-2xl border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-medium text-slate-800">
                  {service.serverUrl || "-"}
                </p>
              </div>
            </div>

            <div className="grid gap-3 text-sm text-slate-700">
              <div className="flex items-center justify-between">
                <span className="text-slate-500">{t("mcpTools.detail.source")}</span>
                <span className="font-medium text-slate-800">{sourceText}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500">{t("mcpTools.detail.serverType")}</span>
                <span className="font-medium text-slate-800">{serverTypeText}</span>
              </div>
              {service.version ? (
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">{t("mcpTools.detail.version")}</span>
                  <span className="font-medium text-slate-800">{formatRegistryVersion(service.version)}</span>
                </div>
              ) : null}
              <div className="flex items-center justify-between">
                <span className="text-slate-500">{t("mcpTools.detail.status")}</span>
                <span className={`rounded-full px-3 py-1 text-xs font-semibold ${statusClassName}`}>
                  {t(statusTextKey)}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500">{t("mcpTools.community.publishedAt")}</span>
                <span className="font-medium text-slate-800">{formatRegistryDate(service.publishedAt || "")}</span>
              </div>
              {websiteUrl ? (
                <div className="flex items-center justify-between gap-4">
                  <span className="text-slate-500">{t("mcpTools.detail.website")}</span>
                  <a
                    href={websiteUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="max-w-[70%] truncate font-medium text-sky-700 hover:text-sky-800"
                  >
                    {websiteUrl}
                  </a>
                </div>
              ) : null}
              {repositoryUrl ? (
                <div className="flex items-center justify-between gap-4">
                  <span className="text-slate-500">{t("mcpTools.detail.repository")}</span>
                  <a
                    href={repositoryUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="max-w-[70%] truncate font-medium text-sky-700 hover:text-sky-800"
                  >
                    {repositoryUrl}
                  </a>
                </div>
              ) : null}
            </div>

            {(service.tags || []).length > 0 ? (
              <div className="space-y-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{t("mcpTools.detail.tags")}</p>
                <div className="flex flex-wrap gap-2">
                  {(service.tags || []).map((tag) => (
                    <span key={`${service.name}-${tag}`} className="rounded-full bg-sky-100 px-2.5 py-1 text-xs font-medium text-sky-700">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}

            <div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-500">{t("mcpTools.detail.tools")}</span>
                <div className="flex items-center gap-2">
                  {hasServerJson ? (
                    <Button size="small" className="rounded-full" autoInsertSpace={false} onClick={() => setShowServerJsonModal(true)}>
                      {t("mcpTools.community.viewServerJson")}
                    </Button>
                  ) : null}
                  {hasConfigJson ? (
                    <Button size="small" className="rounded-full" autoInsertSpace={false} onClick={() => setShowConfigJsonModal(true)}>
                      {t("mcpTools.detail.viewConfigJson")}
                    </Button>
                  ) : null}
                </div>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 border-t border-slate-100 px-6 py-4">
            <Button type="primary" className="rounded-full" onClick={() => onQuickAddFromCommunity(service)}>
              {t("mcpTools.community.quickAdd")}
            </Button>
          </div>
        </div>
      </Modal>

      {showServerJsonModal && hasServerJson ? (
        <Modal
          open
          footer={null}
          closable
          centered
          width={960}
          onCancel={() => setShowServerJsonModal(false)}
          title={t("mcpTools.community.serverJsonTitle", { name: service.name })}
        >
          <pre className="max-h-[65vh] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs text-slate-100">
            {serverJsonPretty}
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
          title={t("mcpTools.detail.configJsonTitle", { name: service.name })}
        >
          <pre className="max-h-[65vh] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs text-slate-100">
            {configJsonPretty}
          </pre>
        </Modal>
      ) : null}
    </>
  );
}
