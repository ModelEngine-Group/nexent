import { Button } from "antd";
import { MCP_REGISTRY_SERVER_STATUS } from "@/const/mcpTools";
import { formatRegistryDate, formatRegistryVersion } from "@/lib/mcpTools";
import type { RegistryMcpCard as RegistryMcpCard } from "@/types/mcpTools";

interface Props {
  service: RegistryMcpCard;
  t: (key: string, params?: Record<string, unknown>) => string;
  onSelectRegistryService: (service: RegistryMcpCard) => void;
  onQuickAddFromRegistry: (service: RegistryMcpCard) => void;
}

export default function McpRegistryCard({
  service,
  t,
  onSelectRegistryService: onSelectRegistryService,
  onQuickAddFromRegistry: onQuickAddFromRegistry,
}: Props) {
  const server = service.server;
  const officialMeta = ((service._meta as Record<string, unknown> | undefined)?.["io.modelcontextprotocol.registry/official"] || {}) as Record<string, unknown>;
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
    <div
      onClick={() => onSelectRegistryService(service)}
      className="group rounded-3xl border border-slate-200/80 bg-white p-5 shadow-sm transition hover:-translate-y-1 hover:shadow-lg"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 break-all text-base font-semibold text-slate-900">{server.name}</h3>
        <span className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold ${statusClassName}`}>
          {t(statusTextKey)}
        </span>
      </div>

      <div className="mt-2 flex items-center gap-2">
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-600">
          {formatRegistryVersion(server.version || "")}
        </span>
        <span className="text-xs text-slate-400">{formatRegistryDate(String(officialMeta.publishedAt || ""))}</span>
      </div>

      <p className="mt-3 line-clamp-2 min-h-[40px] text-sm text-slate-600">{server.description || ""}</p>

      <div className="mt-4 flex items-center justify-end gap-2">
        <Button
          size="small"
          type="primary"
          className="rounded-full"
          onClick={(event) => {
            event.stopPropagation();
            onQuickAddFromRegistry(service);
          }}
        >
          {t("mcpTools.registry.quickAdd")}
        </Button>
      </div>
    </div>
  );
}
