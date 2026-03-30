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
  const server = service.server;
  const officialMeta = ((service._meta as Record<string, unknown> | undefined)?.["io.modelcontextprotocol.registry/official"] || {}) as Record<string, unknown>;
  const { websiteUrl, repositoryUrl } = extractRegistryLinks(server);
  const serverJsonPretty = toPrettyRegistryJson(server);
  const hasServerJson = Boolean(server && Object.keys(server).length > 0);

  const displayRemotes = Array.isArray(server.remotes) ? server.remotes : [];
  const displayPackages = Array.isArray(server.packages)
    ? server.packages.filter((pkg): pkg is Record<string, unknown> => Boolean(pkg) && typeof pkg === "object")
    : [];

  const normalizeHeaderItems = (headers: unknown[]) => {
    return headers.filter((header): header is Record<string, unknown> => Boolean(header) && typeof header === "object");
  };

  const hasRenderableValue = (value: unknown) => {
    if (value === null || value === undefined) return false;
    if (typeof value === "string") return value.trim().length > 0;
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === "object") return Object.keys(value as Record<string, unknown>).length > 0;
    return true;
  };

  const getHeaderFieldLabel = (key: string) => {
    const knownKeyMap: Record<string, string> = {
      name: "mcpTools.registry.headerField.name",
      description: "mcpTools.registry.headerField.description",
      isRequired: "mcpTools.registry.headerField.isRequired",
      isSecret: "mcpTools.registry.headerField.isSecret",
      format: "mcpTools.registry.headerField.format",
      value: "mcpTools.registry.headerField.value",
      default: "mcpTools.registry.headerField.default",
      placeholder: "mcpTools.registry.headerField.placeholder",
      choices: "mcpTools.registry.headerField.choices",
      variables: "mcpTools.registry.headerField.variables",
      type: "mcpTools.registry.headerField.type",
    };
    const translationKey = knownKeyMap[key];
    return translationKey ? t(translationKey) : key;
  };

  const getVariableFieldLabel = (key: string) => {
    const knownKeyMap: Record<string, string> = {
      description: "mcpTools.registry.variableField.description",
      format: "mcpTools.registry.variableField.format",
      value: "mcpTools.registry.variableField.value",
      default: "mcpTools.registry.variableField.default",
      placeholder: "mcpTools.registry.variableField.placeholder",
      choices: "mcpTools.registry.variableField.choices",
      variables: "mcpTools.registry.variableField.variables",
      type: "mcpTools.registry.variableField.type",
      isRequired: "mcpTools.registry.variableField.isRequired",
      isSecret: "mcpTools.registry.variableField.isSecret",
    };
    const translationKey = knownKeyMap[key];
    return translationKey ? t(translationKey) : key;
  };

  const getPackageFieldLabel = (key: string) => {
    const knownKeyMap: Record<string, string> = {
      registryType: "mcpTools.registry.packageField.registryType",
      identifier: "mcpTools.registry.packageField.identifier",
      version: "mcpTools.registry.packageField.version",
      runtimeHint: "mcpTools.registry.packageField.runtimeHint",
      registryBaseUrl: "mcpTools.registry.packageField.registryBaseUrl",
      fileSha256: "mcpTools.registry.packageField.fileSha256",
      environmentVariables: "mcpTools.registry.packageField.environmentVariables",
      runtimeArguments: "mcpTools.registry.packageField.runtimeArguments",
      packageArguments: "mcpTools.registry.packageField.packageArguments",
      transport: "mcpTools.registry.packageField.transport",
    };
    const translationKey = knownKeyMap[key];
    return translationKey ? t(translationKey) : key;
  };

  const formatHeaderFieldValue = (value: unknown) => {
    if (typeof value === "boolean") {
      return value ? t("common.yes") : t("common.no");
    }
    if (typeof value === "string" || typeof value === "number") {
      return String(value);
    }
    return "";
  };

  const renderStructuredValue = (value: unknown, keyPath: string): React.ReactNode => {
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      return <span className="break-all">{formatHeaderFieldValue(value)}</span>;
    }

    if (Array.isArray(value)) {
      if (value.length === 0) {
        return <span className="text-slate-400">-</span>;
      }
      return (
        <div className="mt-1 space-y-1">
          {value.map((item, index) => (
            <div key={`${keyPath}-${index}`} className="rounded border border-slate-200 bg-slate-50 p-2">
              <div className="mb-1 text-[11px] font-medium text-slate-500">#{index + 1}</div>
              {renderStructuredValue(item, `${keyPath}-${index}`)}
            </div>
          ))}
        </div>
      );
    }

    if (value && typeof value === "object") {
      const entries = Object.entries(value as Record<string, unknown>).filter(([, nested]) => hasRenderableValue(nested));
      if (entries.length === 0) {
        return <span className="text-slate-400">-</span>;
      }
      return (
        <div className="mt-1 space-y-1 rounded border border-slate-200 bg-slate-50 p-2">
          {entries.map(([nestedKey, nestedValue]) => (
            <div key={`${keyPath}-${nestedKey}`}>
              <span className="font-medium text-slate-700">{nestedKey}:</span>{" "}
              {renderStructuredValue(nestedValue, `${keyPath}-${nestedKey}`)}
            </div>
          ))}
        </div>
      );
    }

    return <span className="text-slate-400">-</span>;
  };

  const resolveRemoteHeaders = (remote: Record<string, unknown>) => {
    const headers = Array.isArray(remote.headers) ? remote.headers : [];
    return normalizeHeaderItems(headers as unknown[]);
  };

  const resolveRemoteVariables = (remote: Record<string, unknown>) => {
    const variables = remote.variables;
    if (!variables || typeof variables !== "object") {
      return [] as Array<{ key: string; config: Record<string, unknown> }>;
    }

    return Object.entries(variables)
      .filter(([, value]) => Boolean(value) && typeof value === "object")
      .map(([key, value]) => ({ key, config: value as Record<string, unknown> }));
  };

  const officialStatus = String(officialMeta.status || "").toLowerCase();
  const statusClassName =
    officialStatus === MCP_REGISTRY_SERVER_STATUS.ACTIVE
      ? "bg-emerald-100 text-emerald-700"
      : officialStatus === MCP_REGISTRY_SERVER_STATUS.DEPRECATED
      ? "bg-amber-100 text-amber-700"
      : "bg-slate-100 text-slate-600";
  const statusTextKey =
    officialStatus === MCP_REGISTRY_SERVER_STATUS.ACTIVE
      ? "mcpTools.registry.status.active"
      : officialStatus === MCP_REGISTRY_SERVER_STATUS.DEPRECATED
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
                <h3 className="break-all text-2xl font-semibold text-slate-900">{server.name}</h3>
                <p className="mt-1 text-sm text-slate-500">{formatRegistryVersion(server.version || "")}</p>
              </div>
              <span className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${statusClassName}`}>
                {t(statusTextKey)}
              </span>
            </div>
          </div>

          <div className="px-6 py-5 space-y-4">
            <p className="text-sm text-slate-700">{server.description || ""}</p>

            <p className="text-xs text-slate-500">{formatRegistryDate(String(officialMeta.publishedAt || ""))}</p>

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

            {displayRemotes.length > 0 ? (
              <div className="space-y-2">
                <p className="text-sm font-semibold text-slate-900">{t("mcpTools.registry.remotes")}</p>
                <div className="space-y-2">
                  {displayRemotes.map((remote, index) => {
                    const remoteRecord = remote as Record<string, unknown>;
                    const remoteHeaders = resolveRemoteHeaders(remoteRecord);
                    const remoteVariables = resolveRemoteVariables(remoteRecord);
                    const remoteType = String(remoteRecord.type || "");
                    const remoteUrl = String(remoteRecord.url || "");

                    return (
                      <div key={`${server.name}-${remoteUrl}-${index}`} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm">
                        <p className="font-medium text-slate-900">{remoteType || t("mcpTools.registry.remoteFallback")}</p>
                        <p className="break-all text-slate-600">{remoteUrl}</p>
                        {remoteHeaders.length > 0 ? (
                        <div className="mt-2 space-y-2 rounded-lg border border-slate-100 bg-slate-50 p-2">
                          <p className="text-xs font-semibold text-slate-700">{t("mcpTools.registry.remoteHeaders")}</p>
                          {remoteHeaders.map((header, headerIndex) => (
                            <div key={`${server.name}-${remoteUrl}-${String(header.name || headerIndex)}-${headerIndex}`} className="rounded-md border border-slate-200 bg-white p-2">
                              <p className="break-all text-xs font-medium text-slate-900">
                                {typeof header.name === "string" && header.name.trim()
                                  ? header.name
                                  : t("mcpTools.registry.headerFallback", { index: headerIndex + 1 })}
                              </p>
                              <div className="mt-1 space-y-1 text-[11px] text-slate-600">
                                {Object.entries(header)
                                  .filter(([key, value]) => key !== "name" && hasRenderableValue(value))
                                  .map(([key, value]) => (
                                    <div key={`${server.name}-${remoteUrl}-${headerIndex}-${key}`}>
                                      <span className="font-medium text-slate-700">{getHeaderFieldLabel(key)}:</span>{" "}
                                      {renderStructuredValue(value, `${server.name}-${remoteUrl}-${headerIndex}-${key}`)}
                                    </div>
                                  ))}
                              </div>
                            </div>
                          ))}
                        </div>
                        ) : null}
                        {remoteVariables.length > 0 ? (
                          <div className="mt-2 space-y-2 rounded-lg border border-slate-100 bg-slate-50 p-2">
                            <p className="text-xs font-semibold text-slate-700">{t("mcpTools.registry.remoteVariables")}</p>
                            {remoteVariables.map((variable, variableIndex) => (
                              <div key={`${server.name}-${remoteUrl}-${variable.key}-${variableIndex}`} className="rounded-md border border-slate-200 bg-white p-2">
                                <p className="break-all text-xs font-medium text-slate-900">{variable.key}</p>
                                <div className="mt-1 space-y-1 text-[11px] text-slate-600">
                                  {Object.entries(variable.config)
                                    .filter(([, value]) => hasRenderableValue(value))
                                    .map(([fieldKey, fieldValue]) => (
                                      <div key={`${server.name}-${remoteUrl}-${variable.key}-${fieldKey}`}>
                                        <span className="font-medium text-slate-700">{getVariableFieldLabel(fieldKey)}:</span>{" "}
                                        {renderStructuredValue(fieldValue, `${server.name}-${remoteUrl}-${variable.key}-${fieldKey}`)}
                                      </div>
                                    ))}
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : null}

            {displayPackages.length > 0 ? (
              <div className="space-y-2">
                <p className="text-sm font-semibold text-slate-900">{t("mcpTools.registry.packages")}</p>
                <div className="space-y-2">
                  {displayPackages.map((pkg, index) => (
                    <div key={`${server.name}-${String(pkg.identifier || index)}-${String(pkg.version || "")}-${index}`} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm">
                      <p className="font-medium text-slate-900 break-all">{String(pkg.identifier || "-")}</p>
                      <div className="mt-1 space-y-1 text-xs text-slate-600">
                        {Object.entries(pkg)
                          .filter(([, value]) => hasRenderableValue(value))
                          .map(([fieldKey, fieldValue]) => (
                            <div key={`${server.name}-${String(pkg.identifier || index)}-${fieldKey}`}>
                              <span className="font-medium text-slate-700">{getPackageFieldLabel(fieldKey)}:</span>{" "}
                              {renderStructuredValue(fieldValue, `${server.name}-${String(pkg.identifier || index)}-${fieldKey}`)}
                            </div>
                          ))}
                      </div>
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
          title={t("mcpTools.registry.serverJsonTitle", { name: server.name })}
        >
          <pre className="max-h-[65vh] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs text-slate-100">
            {serverJsonPretty}
          </pre>
        </Modal>
      ) : null}
    </>
  );
}
