import { Button } from "antd";
import { useTranslation } from "react-i18next";
import { MCP_SERVICE_STATUS } from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";
import { getSourceLabelKey, getTransportLabelKey } from "@/lib/mcpTools";

interface McpServiceCardProps {
  service: McpServiceItem;
  onSelect: (service: McpServiceItem) => void;
  onToggleEnable: (service: McpServiceItem) => void;
  toggleLoading?: boolean;
}

export default function McpServiceCard({
  service,
  onSelect,
  onToggleEnable,
  toggleLoading = false,
}: McpServiceCardProps) {
  const { t } = useTranslation("common");
  const isEnabled = service.status === MCP_SERVICE_STATUS.ENABLED;

  return (
    <div
      onClick={() => onSelect(service)}
      className="group rounded-3xl border border-slate-200/80 bg-white p-6 shadow-sm transition hover:-translate-y-1 hover:shadow-lg"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3
            className="truncate text-xl font-semibold text-slate-900"
            title={service.name}
          >
            {service.name}
          </h3>
          <p
            className="mt-2 line-clamp-2 break-all text-sm text-slate-600"
            title={service.description}
          >
            {service.description}
          </p>
        </div>
        <span
          className={`shrink-0 whitespace-nowrap rounded-full px-3 py-1 text-xs font-semibold ${
            isEnabled
              ? "bg-emerald-100 text-emerald-700"
              : "bg-slate-100 text-slate-600"
          }`}
        >
          {t(
            isEnabled ? "mcpTools.status.enabled" : "mcpTools.status.disabled"
          )}
        </span>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <span className="rounded-full bg-amber-100 text-amber-700 px-2.5 py-1 text-xs font-medium">
          {t(getSourceLabelKey(service.source))}
        </span>
        <span className="rounded-full bg-green-100 text-green-700 px-2.5 py-1 text-xs font-medium">
          {t(getTransportLabelKey(service.transportType))}
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
          {t(
            isEnabled ? "mcpTools.service.disable" : "mcpTools.service.enable"
          )}
        </Button>
      </div>
    </div>
  );
}
