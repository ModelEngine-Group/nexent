import { Tag } from "antd";
import { useTranslation } from "react-i18next";
import { MCP_GRID_CARD_OUTER, MCP_SERVICE_STATUS } from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";
import { getSourceLabelKey, getTransportLabelKey } from "@/lib/mcpTools";
import StatusBadge from "./shared/StatusBadge";

interface McpServiceCardProps {
  service: McpServiceItem;
  onSelect: (service: McpServiceItem) => void;
}

export default function McpServiceCard({
  service,
  onSelect,
}: McpServiceCardProps) {
  const { t } = useTranslation("common");
  const isEnabled = service.status === MCP_SERVICE_STATUS.ENABLED;

  return (
    <div onClick={() => onSelect(service)} className={MCP_GRID_CARD_OUTER}>
      <div className="flex shrink-0 items-start justify-between gap-2">
        <h3
          className="min-w-0 truncate text-base font-semibold text-slate-900"
          title={service.name}
        >
          {service.name}
        </h3>
        <StatusBadge status={service.status} />
      </div>

      <p
        className="mt-1 min-h-0 flex-1 overflow-hidden break-all text-sm leading-relaxed text-slate-600 line-clamp-4"
        title={service.description}
      >
        {service.description || "-"}
      </p>

      <div className="mt-2 flex min-h-0 shrink-0 flex-wrap gap-1">
        <Tag className="m-0">{t(getSourceLabelKey(service.source))}</Tag>
        <Tag className="m-0">
          {t(getTransportLabelKey(service.transportType))}
        </Tag>
        {service.tags.map((tag) => (
          <Tag key={`${service.name}-${tag}`} className="m-0">
            {tag}
          </Tag>
        ))}
      </div>
    </div>
  );
}
