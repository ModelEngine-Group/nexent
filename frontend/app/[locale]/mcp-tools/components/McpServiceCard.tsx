import { Tag } from "antd";
import { useTranslation } from "react-i18next";
import { MCP_GRID_CARD_OUTER, MCP_GRID_CARD_OUTER_STYLE } from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";
import { getSourceLabelKey, getTransportLabelKey } from "@/lib/mcpTools";
import StatusBadge from "./shared/StatusBadge";
import TransportIcon from "./shared/TransportIcon";

interface McpServiceCardProps {
  service: McpServiceItem;
  onSelect: (service: McpServiceItem) => void;
}

export default function McpServiceCard({
  service,
  onSelect,
}: McpServiceCardProps) {
  const { t } = useTranslation("common");
  const transportLabel = t(getTransportLabelKey(service.transportType));
  const sourceLabel = t(getSourceLabelKey(service.source));

  return (
    <div
      onClick={() => onSelect(service)}
      className={MCP_GRID_CARD_OUTER}
      style={MCP_GRID_CARD_OUTER_STYLE}
    >
      <div className="flex shrink-0 items-center gap-3">
        <TransportIcon
          transportType={service.transportType}
          label={transportLabel}
        />
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-start justify-between gap-2">
            <h3
              className="min-w-0 truncate text-base font-semibold text-slate-900"
              title={service.name}
            >
              {service.name}
            </h3>
            <StatusBadge status={service.enabled} />
          </div>
          <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-slate-500">
            <span className="truncate">{sourceLabel}</span>
            <span className="text-slate-300">·</span>
            <span className="truncate">{transportLabel}</span>
          </div>
        </div>
      </div>

      <div className="mt-2 flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <p
          className="line-clamp-3 min-w-0 break-all text-sm leading-relaxed text-slate-600"
          title={service.description}
        >
          {service.description || "-"}
        </p>
      </div>

      {service.tags.length > 0 ? (
        <div className="mt-2 flex min-h-0 shrink-0 flex-wrap gap-1">
          {service.tags.map((tag) => (
            <Tag key={`${service.name}-${tag}`} className="m-0">
              {tag}
            </Tag>
          ))}
        </div>
      ) : null}
    </div>
  );
}
