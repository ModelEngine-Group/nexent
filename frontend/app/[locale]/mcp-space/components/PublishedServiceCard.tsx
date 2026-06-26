import { Tag } from "antd";
import { useTranslation } from "react-i18next";
import {
  MCP_GRID_CARD_OUTER,
  MCP_GRID_CARD_OUTER_STYLE,
} from "@/const/mcpTools";
import type { CommunityMcpCard } from "@/types/mcpTools";
import { getTransportLabelKey } from "@/lib/mcpTools";
import TransportIcon from "./shared/TransportIcon";

interface PublishedServiceCardProps {
  service: CommunityMcpCard;
  onSelect: (service: CommunityMcpCard) => void;
}

export default function PublishedServiceCard({
  service,
  onSelect,
}: PublishedServiceCardProps) {
  const { t } = useTranslation("common");
  const version = (service.version || "").trim();
  const tags = service.tags || [];
  const transportLabel = t(getTransportLabelKey(service.transportType));

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
            {version ? (
              <span className="shrink-0 whitespace-nowrap rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                v{version}
              </span>
            ) : null}
          </div>
          <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-xs text-slate-500">
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

      {tags.length > 0 ? (
        <div className="mt-2 flex min-h-0 shrink-0 flex-wrap gap-1">
          {tags.map((tag) => (
            <Tag key={`${service.communityId}-${tag}`} className="m-0">
              {tag}
            </Tag>
          ))}
        </div>
      ) : null}
    </div>
  );
}
