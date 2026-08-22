import { Button } from "antd";
import { useTranslation } from "react-i18next";
import type { CommunityMcpCard } from "@/types/mcpTools";
import McpCommunityCard from "./McpCommunityCard";

interface McpCommunityCardListProps {
  loading: boolean;
  services: CommunityMcpCard[];
  hasPrevPage: boolean;
  hasNextPage: boolean;
  onPrevPage: () => void;
  onNextPage: () => void;
  onSelect: (service: CommunityMcpCard) => void;
  onQuickAdd: (service: CommunityMcpCard) => void;
}

export default function McpCommunityCardList({
  loading,
  services,
  hasPrevPage,
  hasNextPage,
  onPrevPage,
  onNextPage,
  onSelect,
  onQuickAdd,
}: McpCommunityCardListProps) {
  const { t } = useTranslation("common");

  if (loading) {
    return (
      <div className="rounded-md border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center text-slate-500">
        {t("mcpTools.community.loading")}
      </div>
    );
  }

  if (services.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center text-slate-500">
        {t("mcpTools.community.empty")}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
        {services.map((service, index) => (
          <McpCommunityCard
            key={`${service.name}::${service.version || "-"}::${service.createdAt || "-"}::${index}`}
            service={service}
            onSelect={onSelect}
            onQuickAdd={onQuickAdd}
          />
        ))}
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-3">
        <Button onClick={onPrevPage} disabled={!hasPrevPage || loading}>
          {t("mcpTools.community.prevPage")}
        </Button>
        <Button onClick={onNextPage} disabled={!hasNextPage || loading}>
          {t("mcpTools.community.nextPage")}
        </Button>
      </div>
    </div>
  );
}
