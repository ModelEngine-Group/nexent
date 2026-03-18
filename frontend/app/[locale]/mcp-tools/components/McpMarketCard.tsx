import { Button } from "antd";
import { MARKET_SERVER_STATUS } from "@/const/mcpTools";
import { formatMarketDate, formatMarketVersion } from "@/lib/mcpTools";
import type { MarketMcpCard } from "@/types/mcpTools";

interface Props {
  service: MarketMcpCard;
  t: (key: string, params?: Record<string, unknown>) => string;
  onSelectMarketService: (service: MarketMcpCard) => void;
  onQuickAddFromMarket: (service: MarketMcpCard) => void;
}

export default function McpMarketCard({
  service,
  t,
  onSelectMarketService,
  onQuickAddFromMarket,
}: Props) {
  const statusClassName =
    service.status === MARKET_SERVER_STATUS.ACTIVE
      ? "bg-emerald-100 text-emerald-700"
      : service.status === MARKET_SERVER_STATUS.DEPRECATED
      ? "bg-amber-100 text-amber-700"
      : "bg-slate-100 text-slate-600";
  const statusTextKey =
    service.status === MARKET_SERVER_STATUS.ACTIVE
      ? "mcpTools.market.status.active"
      : service.status === MARKET_SERVER_STATUS.DEPRECATED
      ? "mcpTools.market.status.deprecated"
      : "mcpTools.market.status.unknown";

  return (
    <div
      onClick={() => onSelectMarketService(service)}
      className="group rounded-3xl border border-slate-200/80 bg-white p-5 shadow-sm transition hover:-translate-y-1 hover:shadow-lg"
    >
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 break-all text-base font-semibold text-slate-900">{service.name}</h3>
        <span className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold ${statusClassName}`}>
          {t(statusTextKey)}
        </span>
      </div>

      <div className="mt-2 flex items-center gap-2">
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-600">
          {formatMarketVersion(service.version)}
        </span>
        <span className="text-xs text-slate-400">{formatMarketDate(service.publishedAt)}</span>
      </div>

      <p className="mt-3 line-clamp-2 min-h-[40px] text-sm text-slate-600">{service.description}</p>

      <div className="mt-4 flex items-center justify-end gap-2">
        <Button
          size="small"
          type="primary"
          className="rounded-full"
          onClick={(event) => {
            event.stopPropagation();
            onQuickAddFromMarket(service);
          }}
        >
          {t("mcpTools.market.quickAdd")}
        </Button>
      </div>
    </div>
  );
}
