import { Button } from "antd";
import { useTranslation } from "react-i18next";
import type { RegistryMcpCard } from "@/types/mcpTools";
import McpRegistryCard from "./McpRegistryCard";

interface McpRegistryCardListProps {
  loading: boolean;
  services: RegistryMcpCard[];
  hasPrevPage: boolean;
  hasNextPage: boolean;
  onPrevPage: () => void;
  onNextPage: () => void;
  onSelect: (service: RegistryMcpCard) => void;
  onQuickAdd: (service: RegistryMcpCard) => void;
}

export default function McpRegistryCardList({
  loading,
  services,
  hasPrevPage,
  hasNextPage,
  onPrevPage,
  onNextPage,
  onSelect,
  onQuickAdd,
}: McpRegistryCardListProps) {
  const { t } = useTranslation("common");

  if (loading) {
    return (
      <div className="rounded-md border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center text-slate-500">
        {t("mcpTools.registry.loading")}
      </div>
    );
  }

  if (services.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center text-slate-500">
        {t("mcpTools.registry.empty")}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
        {services.map((service, index) => (
          <McpRegistryCard
            key={`${service.name}::${service.version || "-"}::${service.publishedAt || "-"}::${index}`}
            service={service}
            onSelect={onSelect}
            onQuickAdd={onQuickAdd}
          />
        ))}
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-3">
        <Button onClick={onPrevPage} disabled={!hasPrevPage || loading}>
          {t("mcpTools.registry.prevPage")}
        </Button>
        <Button onClick={onNextPage} disabled={!hasNextPage || loading}>
          {t("mcpTools.registry.nextPage")}
        </Button>
      </div>
    </div>
  );
}
