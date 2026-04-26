import { Tag } from "antd";
import { useTranslation } from "react-i18next";
import { MCP_GRID_CARD_OUTER } from "@/const/mcpTools";
import type { CommunityMcpCard } from "@/types/mcpTools";
import { getTransportLabelKey } from "@/lib/mcpTools";

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

  return (
    <div onClick={() => onSelect(service)} className={MCP_GRID_CARD_OUTER}>
      <div className="flex shrink-0 items-start justify-between gap-2">
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

      <p
        className="mt-1 min-h-0 flex-1 overflow-hidden break-all text-sm leading-relaxed text-slate-600 line-clamp-4"
        title={service.description}
      >
        {service.description || "-"}
      </p>

      <div className="mt-2 flex min-h-0 shrink-0 flex-wrap gap-1">
        <Tag className="m-0">
          {t(getTransportLabelKey(service.transportType))}
        </Tag>
        {tags.map((tag) => (
          <Tag key={`${service.communityId}-${tag}`} className="m-0">
            {tag}
          </Tag>
        ))}
      </div>
    </div>
  );
}
