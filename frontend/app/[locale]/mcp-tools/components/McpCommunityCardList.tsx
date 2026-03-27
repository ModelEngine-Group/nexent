import { Button } from "antd";
import type { CommunityMcpCard } from "@/types/mcpTools";
import McpCommunityCard from "./McpCommunityCard";

interface Props {
  communityLoading: boolean;
  services: CommunityMcpCard[];
  hasPrevCommunityPage: boolean;
  hasNextCommunityPage: boolean;
  onPrevCommunityPage: () => void;
  onNextCommunityPage: () => void;
  onSelectCommunityService: (service: CommunityMcpCard) => void;
  onQuickAddFromCommunity: (service: CommunityMcpCard) => void;
  t: (key: string, params?: Record<string, unknown>) => string;
}

export default function McpCommunityCardList({
  communityLoading,
  services,
  hasPrevCommunityPage,
  hasNextCommunityPage,
  onPrevCommunityPage,
  onNextCommunityPage,
  onSelectCommunityService,
  onQuickAddFromCommunity,
  t,
}: Props) {
  if (communityLoading) {
    return (
      <div className="rounded-3xl border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center text-slate-500">
        {t("mcpTools.community.loading")}
      </div>
    );
  }

  if (services.length === 0) {
    return (
      <div className="rounded-3xl border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center text-slate-500">
        {t("mcpTools.community.empty")}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5 max-h-[55vh] overflow-y-auto pr-1">
        {services.map((service, index) => (
          <McpCommunityCard
            key={`${service.name}::${service.version || "-"}::${service.publishedAt || "-"}::${index}`}
            service={service}
            t={t}
            onSelectCommunityService={onSelectCommunityService}
            onQuickAddFromCommunity={onQuickAddFromCommunity}
          />
        ))}
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-3">
        <Button className="rounded-full" onClick={onPrevCommunityPage} disabled={!hasPrevCommunityPage || communityLoading}>
          {t("mcpTools.community.prevPage")}
        </Button>
        <Button className="rounded-full" onClick={onNextCommunityPage} disabled={!hasNextCommunityPage || communityLoading}>
          {t("mcpTools.community.nextPage")}
        </Button>
      </div>
    </div>
  );
}
