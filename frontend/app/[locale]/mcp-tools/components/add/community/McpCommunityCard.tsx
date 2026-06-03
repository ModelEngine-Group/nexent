import { Button, Tag } from "antd";
import { useTranslation } from "react-i18next";
import {
  MCP_GRID_CARD_OUTER,
  MCP_GRID_CARD_OUTER_STYLE,
} from "@/const/mcpTools";
import {
  formatRegistryDate,
  formatRegistryVersion,
  getTransportLabelKey,
} from "@/lib/mcpTools";
import type { CommunityMcpCard } from "@/types/mcpTools";
import RegistryStatusBadge from "../../shared/StatusBadge";

interface McpCommunityCardProps {
  service: CommunityMcpCard;
  onSelect: (service: CommunityMcpCard) => void;
  onQuickAdd: (service: CommunityMcpCard) => void;
}

export default function McpCommunityCard({
  service,
  onSelect,
  onQuickAdd,
}: McpCommunityCardProps) {
  const { t } = useTranslation("common");
  const transportLabel = t(getTransportLabelKey(service.transportType));
  const tags = service.tags || [];

  return (
    <div
      onClick={() => onSelect(service)}
      className={MCP_GRID_CARD_OUTER}
      style={MCP_GRID_CARD_OUTER_STYLE}
    >
      <div className="flex shrink-0 items-start justify-between gap-2">
        <h3
          className="min-w-0 truncate text-base font-semibold text-slate-900"
          title={service.name}
        >
          {service.name}
        </h3>
        <RegistryStatusBadge status={service.status} />
      </div>

      <div className="mt-1 flex shrink-0 items-center gap-2 text-xs text-slate-500">
        <Tag className="m-0 text-[11px]">
          {formatRegistryVersion(service.version || "")}
        </Tag>
        <span className="truncate">
          {formatRegistryDate(service.createdAt || "")}
        </span>
      </div>

      <div className="mt-1 flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        <p
          className="line-clamp-2 min-w-0 break-all text-sm leading-relaxed text-slate-600"
          title={service.description}
        >
          {service.description || "-"}
        </p>
      </div>

      <div className="mt-1 flex min-h-0 max-h-16 shrink-0 flex-wrap content-start gap-1 overflow-hidden">
        <Tag className="m-0">{transportLabel}</Tag>
        {tags.map((tag) => (
          <Tag key={`${service.name}-${tag}`} className="m-0">
            {tag}
          </Tag>
        ))}
      </div>

      <div className="mt-2 flex shrink-0 justify-end">
        <Button
          size="small"
          type="primary"
          onClick={(event) => {
            event.stopPropagation();
            onQuickAdd(service);
          }}
        >
          {t("mcpTools.community.quickAdd")}
        </Button>
      </div>
    </div>
  );
}
