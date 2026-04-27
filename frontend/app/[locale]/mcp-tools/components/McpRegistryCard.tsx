import { Button, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { MCP_GRID_CARD_OUTER } from "@/const/mcpTools";
import { formatRegistryDate, formatRegistryVersion } from "@/lib/mcpTools";
import type { RegistryMcpCard } from "@/types/mcpTools";
import RegistryStatusBadge from "./shared/StatusBadge";

interface McpRegistryCardProps {
  service: RegistryMcpCard;
  onSelect: (service: RegistryMcpCard) => void;
  onQuickAdd: (service: RegistryMcpCard) => void;
}

export default function McpRegistryCard({
  service,
  onSelect,
  onQuickAdd,
}: McpRegistryCardProps) {
  const { t } = useTranslation("common");
  const server = service.server;
  const officialMeta = ((
    service._meta as Record<string, unknown> | undefined
  )?.["io.modelcontextprotocol.registry/official"] || {}) as Record<
    string,
    unknown
  >;

  return (
    <div onClick={() => onSelect(service)} className={MCP_GRID_CARD_OUTER}>
      <div className="flex shrink-0 items-start justify-between gap-2">
        <h3
          className="min-w-0 truncate text-base font-semibold text-slate-900"
          title={server.name}
        >
          {server.name}
        </h3>
        <RegistryStatusBadge
          status={officialMeta.status as string | undefined}
        />
      </div>

      <div className="mt-1 flex shrink-0 items-center gap-2 text-xs text-slate-500">
        <Tag className="m-0 text-[11px]">
          {formatRegistryVersion(server.version || "")}
        </Tag>
        <span className="truncate">
          {formatRegistryDate(String(officialMeta.publishedAt || ""))}
        </span>
      </div>

      <p className="mt-1 min-h-0 flex-1 overflow-hidden break-all text-sm text-slate-600 line-clamp-3">
        {server.description || ""}
      </p>

      <div className="mt-2 flex shrink-0 justify-end">
        <Button
          size="small"
          type="primary"
          onClick={(event) => {
            event.stopPropagation();
            onQuickAdd(service);
          }}
        >
          {t("mcpTools.registry.quickAdd")}
        </Button>
      </div>
    </div>
  );
}
