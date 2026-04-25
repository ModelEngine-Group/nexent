import { Button } from "antd";
import { useTranslation } from "react-i18next";
import {
  formatRegistryDate,
  formatRegistryVersion,
  getTransportLabelKey,
} from "@/lib/mcpTools";
import type { CommunityMcpCard } from "@/types/mcpTools";
import RegistryStatusBadge from "./shared/RegistryStatusBadge";

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

  return (
    <div
      onClick={() => onSelect(service)}
      className="group rounded-3xl border border-slate-200/80 bg-white p-5 shadow-sm transition hover:-translate-y-1 hover:shadow-lg"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 break-all text-base font-semibold text-slate-900">
          {service.name}
        </h3>
        <RegistryStatusBadge status={service.status} variant="community" />
      </div>

      <div className="mt-2 flex items-center gap-2">
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-600">
          {formatRegistryVersion(service.version || "")}
        </span>
        <span className="text-xs text-slate-400">
          {formatRegistryDate(service.publishedAt || "")}
        </span>
      </div>

      <p className="mt-3 line-clamp-2 min-h-[40px] text-sm text-slate-600">
        {service.description}
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        <span className="rounded-full bg-green-100 px-2.5 py-1 text-xs font-medium text-green-700">
          {transportLabel}
        </span>
        {(service.tags || []).map((tag) => (
          <span
            key={`${service.name}-${tag}`}
            className="rounded-full bg-sky-100 px-2.5 py-1 text-xs font-medium text-sky-700"
          >
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
            onQuickAdd(service);
          }}
        >
          {t("mcpTools.community.quickAdd")}
        </Button>
      </div>
    </div>
  );
}
