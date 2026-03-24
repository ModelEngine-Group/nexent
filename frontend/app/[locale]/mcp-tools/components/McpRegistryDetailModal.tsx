import { useState } from "react";
import { Button, Modal } from "antd";
import { MCP_REGISTRY_SERVER_STATUS } from "@/const/mcpTools";
import {
  extractRegistryLinks,
  formatRegistryDate,
  formatRegistryVersion,
  toPrettyRegistryJson,
} from "@/lib/mcpTools";
import type { RegistryMcpCard } from "@/types/mcpTools";

interface Props {
  service: RegistryMcpCard;
  t: (key: string, params?: Record<string, unknown>) => string;
  onClose: () => void;
  onQuickAddFromRegistry: (service: RegistryMcpCard) => void;
}

export default function McpRegistryDetailModal({
  service,
  t,
  onClose,
  onQuickAddFromRegistry: onQuickAddFromRegistry,
}: Props) {
  const [showServerJsonModal, setShowServerJsonModal] = useState(false);
  const { websiteUrl, repositoryUrl } = extractRegistryLinks(service.serverJson);
  const serverJsonPretty = toPrettyRegistryJson(service.serverJson);
  const hasServerJson = Boolean(service.serverJson && Object.keys(service.serverJson).length > 0);

  const statusClassName =
    service.status === MCP_REGISTRY_SERVER_STATUS.ACTIVE
      ? "bg-emerald-100 text-emerald-700"
      : service.status === MCP_REGISTRY_SERVER_STATUS.DEPRECATED
      ? "bg-amber-100 text-amber-700"
      : "bg-slate-100 text-slate-600";
  const statusTextKey =
    service.status === MCP_REGISTRY_SERVER_STATUS.ACTIVE
      ? "mcpTools.registry.status.active"
      : service.status === MCP_REGISTRY_SERVER_STATUS.DEPRECATED
      ? "mcpTools.registry.status.deprecated"
      : "mcpTools.registry.status.unknown";

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
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="break-all text-2xl font-semibold text-slate-900">{service.name}</h3>
                <p className="mt-1 text-sm text-slate-500">{formatRegistryVersion(service.version)}</p>
              </div>
              <span className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${statusClassName}`}>
                {t(statusTextKey)}
              </span>
            </div>
          </div>

          <div className="px-6 py-5 space-y-4">
            <p className="text-sm text-slate-700">{service.description}</p>

            <p className="text-xs text-slate-500">{formatRegistryDate(service.publishedAt)}</p>

            {websiteUrl || repositoryUrl ? (
              <div className="grid grid-cols-1 gap-3 rounded-2xl border border-slate-100 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                {websiteUrl ? (
                  <div className="flex flex-wrap gap-2">
                    <span className="text-slate-500">{t("mcpTools.registry.website")}</span>
                    <a
                      href={websiteUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="break-all font-medium text-sky-700 hover:text-sky-600"
                    >
                      {websiteUrl}
                    </a>
                  </div>
                ) : null}

                {repositoryUrl ? (
                  <div className="flex flex-wrap gap-2">
                    <span className="text-slate-500">{t("mcpTools.registry.repository")}</span>
                    <a
                      href={repositoryUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="break-all font-medium text-sky-700 hover:text-sky-600"
                    >
                      {repositoryUrl}
                    </a>
                  </div>
                ) : null}
              </div>
            ) : null}

            {service.remotes.length > 0 ? (
              <div className="space-y-2">
                <p className="text-sm font-semibold text-slate-900">{t("mcpTools.registry.remotes")}</p>
                <div className="space-y-2">
                  {service.remotes.map((remote, index) => (
                    <div key={`${service.name}-${remote.url}-${index}`} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm">
                      <p className="font-medium text-slate-900">{remote.type || t("mcpTools.registry.remoteFallback")}</p>
                      <p className="break-all text-slate-600">{remote.url}</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {service.packages.length > 0 ? (
              <div className="space-y-2">
                <p className="text-sm font-semibold text-slate-900">{t("mcpTools.registry.packages")}</p>
                <div className="space-y-2">
                  {service.packages.map((pkg, index) => (
                    <div key={`${service.name}-${pkg.registryType}-${pkg.identifier}-${pkg.version}-${index}`} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm">
                      <p className="font-medium text-slate-900 break-all">{pkg.identifier || "-"}</p>
                      <p className="text-slate-600">{pkg.registryType || "-"}{pkg.version ? `@${pkg.version}` : ""}</p>
                      {pkg.runtimeHint ? <p className="text-slate-500">{pkg.runtimeHint}</p> : null}
                      {pkg.transport?.url ? (
                        <p className="break-all text-slate-600">{pkg.transport.type || t("mcpTools.registry.remoteFallback")}: {pkg.transport.url}</p>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>

          <div className="flex items-center justify-end gap-3 border-t border-slate-100 px-6 py-4">
            {hasServerJson ? (
              <Button className="rounded-full" onClick={() => setShowServerJsonModal(true)}>
                {t("mcpTools.registry.viewServerJson")}
              </Button>
            ) : null}
            <Button type="primary" className="rounded-full" onClick={() => onQuickAddFromRegistry(service)}>
              {t("mcpTools.registry.quickAdd")}
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
          title={t("mcpTools.registry.serverJsonTitle", { name: service.name })}
        >
          <pre className="max-h-[65vh] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs text-slate-100">
            {serverJsonPretty}
          </pre>
        </Modal>
      ) : null}
    </>
  );
}
