import { Button } from "antd";
import type { MarketMcpCard } from "@/types/mcpTools";
import McpMarketCard from "./McpMarketCard";

interface Props {
  marketLoading: boolean;
  services: MarketMcpCard[];
  hasPrevMarketPage: boolean;
  hasNextMarketPage: boolean;
  onPrevMarketPage: () => void;
  onNextMarketPage: () => void;
  onSelectMarketService: (service: MarketMcpCard) => void;
  onQuickAddFromMarket: (service: MarketMcpCard) => void;
  t: (key: string, params?: Record<string, unknown>) => string;
}

export default function McpMarketCardList({
  marketLoading,
  services,
  hasPrevMarketPage,
  hasNextMarketPage,
  onPrevMarketPage,
  onNextMarketPage,
  onSelectMarketService,
  onQuickAddFromMarket,
  t,
}: Props) {
  if (marketLoading) {
    return (
      <div className="rounded-3xl border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center text-slate-500">
        {t("mcpTools.market.loading")}
      </div>
    );
  }

  if (services.length === 0) {
    return (
      <div className="rounded-3xl border border-dashed border-slate-200 bg-slate-50 px-6 py-10 text-center text-slate-500">
        {t("mcpTools.market.empty")}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5 max-h-[55vh] overflow-y-auto pr-1">
        {services.map((service, index) => (
          <McpMarketCard
            key={`${service.name}::${service.version || "-"}::${service.publishedAt || "-"}::${index}`}
            service={service}
            t={t}
            onSelectMarketService={onSelectMarketService}
            onQuickAddFromMarket={onQuickAddFromMarket}
          />
        ))}
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-3">
        <Button className="rounded-full" onClick={onPrevMarketPage} disabled={!hasPrevMarketPage || marketLoading}>
          {t("mcpTools.market.prevPage")}
        </Button>
        <Button className="rounded-full" onClick={onNextMarketPage} disabled={!hasNextMarketPage || marketLoading}>
          {t("mcpTools.market.nextPage")}
        </Button>
      </div>
    </div>
  );
}
