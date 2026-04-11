import { Button } from "antd";
import { MCP_TRANSPORT_TYPE, MCP_REGISTRY_SERVER_STATUS } from "@/const/mcpTools";
import { formatRegistryDate, formatRegistryVersion } from "@/lib/mcpTools";
import type { CommunityMcpCard } from "@/types/mcpTools";

interface Props {
  service: CommunityMcpCard;
  t: (key: string, params?: Record<string, unknown>) => string;
  onSelectCommunityService: (service: CommunityMcpCard) => void;
  onQuickAddFromCommunity: (service: CommunityMcpCard) => void;
}

export default function McpCommunityCard({
  service,
  t,
  onSelectCommunityService,
  onQuickAddFromCommunity,
}: Props) {
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
    <div
      onClick={() => onSelectCommunityService(service)}
      className="group rounded-3xl border border-slate-200/80 bg-white p-5 shadow-sm transition hover:-translate-y-1 hover:shadow-lg"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 break-all text-base font-semibold text-slate-900">{service.name}</h3>
        <span className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold ${statusClassName}`}>
          {t(statusTextKey)}
        </span>
      </div>

      <div className="mt-2 flex items-center gap-2">
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-600">
          {formatRegistryVersion(service.version || "")}
        </span>
        <span className="text-xs text-slate-400">{formatRegistryDate(service.publishedAt || "")}</span>
      </div>

      <p className="mt-3 line-clamp-2 min-h-[40px] text-sm text-slate-600">{service.description}</p>

      <div className="mt-4 flex flex-wrap gap-2">
        <span className="rounded-full bg-green-100 px-2.5 py-1 text-xs font-medium text-green-700">
          {service.transportType === MCP_TRANSPORT_TYPE.HTTP
            ? t("mcpTools.serverType.http")
            : service.transportType === MCP_TRANSPORT_TYPE.SSE
            ? t("mcpTools.serverType.sse")
            : t("mcpTools.serverType.container")}
        </span>
        {(service.tags || []).map((tag) => (
          <span key={`${service.name}-${tag}`} className="rounded-full bg-sky-100 px-2.5 py-1 text-xs font-medium text-sky-700">
            {tag}
          </span>
        ))}
      </div>

      <div className="mt-4 flex items-center justify-end gap-2">
        <Button
          size="small"
          type="primary"
          className="rounded-full"
          onClick={(event) => {
            event.stopPropagation();
            onQuickAddFromCommunity(service);
          }}
        >
          {t("mcpTools.community.quickAdd")}
        </Button>
      </div>
    </div>
  );
}
