import { Button } from "antd";
import { useTranslation } from "react-i18next";
import { formatRegistryDate, formatRegistryVersion } from "@/lib/mcpTools";
import type { RegistryMcpCard } from "@/types/mcpTools";
import RegistryStatusBadge from "./shared/RegistryStatusBadge";

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
    <div
      onClick={() => onSelect(service)}
      className="group rounded-3xl border border-slate-200/80 bg-white p-5 shadow-sm transition hover:-translate-y-1 hover:shadow-lg"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 break-all text-base font-semibold text-slate-900">
          {server.name}
        </h3>
        <RegistryStatusBadge
          status={officialMeta.status as string | undefined}
        />
      </div>

      <div className="mt-2 flex items-center gap-2">
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-600">
          {formatRegistryVersion(server.version || "")}
        </span>
        <span className="text-xs text-slate-400">
          {formatRegistryDate(String(officialMeta.publishedAt || ""))}
        </span>
      </div>

      <p className="mt-3 line-clamp-2 min-h-[40px] text-sm text-slate-600">
        {server.description || ""}
      </p>

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
          {t("mcpTools.registry.quickAdd")}
        </Button>
      </div>
    </div>
  );
}
