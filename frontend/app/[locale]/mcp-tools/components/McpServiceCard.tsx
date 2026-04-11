import { Button } from "antd";
import { MCP_TRANSPORT_TYPE, MCP_SERVICE_STATUS, MCP_TAB } from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";

type Translate = (key: string, options?: Record<string, unknown>) => React.ReactNode;

interface Props {
  service: McpServiceItem;
  t: Translate;
  onSelectService: (service: McpServiceItem) => void;
  onToggleEnable: (service: McpServiceItem) => void;
  toggleLoading?: boolean;
}

export default function McpServiceCard({
  service,
  t,
  onSelectService,
  onToggleEnable,
  toggleLoading = false,
}: Props) {
  return (
    <div
      onClick={() => onSelectService(service)}
      className="group rounded-3xl border border-slate-200/80 bg-white p-6 shadow-sm transition hover:-translate-y-1 hover:shadow-lg"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-xl font-semibold text-slate-900" title={service.name}>
            {service.name}
          </h3>
          <p className="mt-2 line-clamp-2 break-all text-sm text-slate-600" title={service.description}>
            {service.description}
          </p>
        </div>
        <span
          className={`shrink-0 whitespace-nowrap rounded-full px-3 py-1 text-xs font-semibold ${
            service.status === MCP_SERVICE_STATUS.ENABLED
              ? "bg-emerald-100 text-emerald-700"
              : "bg-slate-100 text-slate-600"
          }`}
        >
          {service.status === MCP_SERVICE_STATUS.ENABLED
            ? t("mcpTools.status.enabled")
            : t("mcpTools.status.disabled")}
        </span>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <span className="rounded-full bg-amber-100 text-amber-700 px-2.5 py-1 text-xs font-medium">
          {service.source === MCP_TAB.LOCAL
            ? t("mcpTools.source.local")
            : service.source === MCP_TAB.COMMUNITY
            ? t("mcpTools.source.community")
            : t("mcpTools.source.registry")}
        </span>
        <span className="rounded-full bg-green-100 text-green-700 px-2.5 py-1 text-xs font-medium">
          {service.transportType === MCP_TRANSPORT_TYPE.HTTP
            ? t("mcpTools.serverType.http")
            : service.transportType === MCP_TRANSPORT_TYPE.SSE
            ? t("mcpTools.serverType.sse")
            : t("mcpTools.serverType.container")}
        </span>
        {service.tags.map((tag) => (
          <span
            key={`${service.name}-${tag}`}
            className="rounded-full bg-sky-100 text-sky-700 px-2.5 py-1 text-xs font-medium"
          >
            {tag}
          </span>
        ))}
      </div>

      <div className="mt-5 flex items-center justify-end text-xs text-slate-500">
        <div className="flex items-center gap-2">
          <Button
            size="small"
            className="rounded-full"
            autoInsertSpace={false}
            loading={toggleLoading}
            disabled={toggleLoading}
            onClick={(event) => {
              event.stopPropagation();
              onToggleEnable(service);
            }}
          >
            {service.status === MCP_SERVICE_STATUS.ENABLED
              ? t("mcpTools.service.disable")
              : t("mcpTools.service.enable")}
          </Button>
        </div>
      </div>
    </div>
  );
}
