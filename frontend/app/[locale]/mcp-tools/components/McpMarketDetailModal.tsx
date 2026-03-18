import { useMemo, useState } from "react";
import { Button, Modal } from "antd";
import { MARKET_SERVER_STATUS } from "@/const/mcpTools";
import { formatMarketDate, formatMarketVersion } from "@/lib/mcpTools";
import type { MarketMcpCard } from "@/types/mcpTools";

interface Props {
  service: MarketMcpCard;
  t: (key: string, params?: Record<string, unknown>) => string;
  onClose: () => void;
  onQuickAddFromMarket: (service: MarketMcpCard) => void;
}

export default function McpMarketDetailModal({
  service,
  t,
  onClose,
  onQuickAddFromMarket,
}: Props) {
  const [showServerJsonModal, setShowServerJsonModal] = useState(false);

  const serverJsonPretty = useMemo(() => {
    return JSON.stringify(service.serverJson || {}, null, 2);
  }, [service.serverJson]);

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
    <>
      <Modal
        open
        footer={null}
        closable
        maskClosable={false}
        centered
        width={900}
        onCancel={onClose}
        styles={{
          mask: { background: "rgba(15,23,42,0.4)" },
          body: { padding: 0 },
        }}
      >
        <div>
          <div className="border-b border-slate-100 px-6 py-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="break-all text-2xl font-semibold text-slate-900">{service.name}</h3>
                <p className="mt-1 text-sm text-slate-500">{formatMarketVersion(service.version)}</p>
              </div>
              <span className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${statusClassName}`}>
                {t(statusTextKey)}
              </span>
            </div>
          </div>

          <div className="px-6 py-5 space-y-4">
            <p className="text-sm text-slate-700">{service.description}</p>

            <p className="text-xs text-slate-500">{formatMarketDate(service.publishedAt)}</p>

            <div className="grid grid-cols-1 gap-3 rounded-2xl border border-slate-100 bg-slate-50 px-4 py-3 text-sm text-slate-700">
              <div className="flex flex-wrap gap-2">
                <span className="text-slate-500">{t("mcpTools.market.title")}</span>
                <span className="font-medium text-slate-900">{service.title || "-"}</span>
              </div>
              <div className="flex flex-wrap gap-2">
                <span className="text-slate-500">{t("mcpTools.market.website")}</span>
                {service.websiteUrl ? (
                  <a
                    href={service.websiteUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="break-all font-medium text-sky-700 hover:text-sky-600"
                  >
                    {service.websiteUrl}
                  </a>
                ) : (
                  <span className="font-medium text-slate-900">-</span>
                )}
              </div>
            </div>

            <div className="space-y-2">
              <p className="text-sm font-semibold text-slate-900">{t("mcpTools.market.remotes")}</p>
              {service.remotes.length === 0 ? (
                <p className="text-sm text-slate-500">{t("mcpTools.market.noRemotes")}</p>
              ) : (
                <div className="space-y-2">
                  {service.remotes.map((remote, index) => (
                    <div key={`${service.name}-${remote.url}-${index}`} className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm">
                      <p className="font-medium text-slate-900">{remote.type || t("mcpTools.market.remoteFallback")}</p>
                      <p className="break-all text-slate-600">{remote.url}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 border-t border-slate-100 px-6 py-4">
            <Button className="rounded-full" onClick={() => setShowServerJsonModal(true)}>
              {t("mcpTools.market.viewServerJson")}
            </Button>
            <Button type="primary" className="rounded-full" onClick={() => onQuickAddFromMarket(service)}>
              {t("mcpTools.market.quickAdd")}
            </Button>
          </div>
        </div>
      </Modal>

      {showServerJsonModal ? (
        <Modal
          open
          footer={null}
          closable
          centered
          width={960}
          onCancel={() => setShowServerJsonModal(false)}
          title={t("mcpTools.market.serverJsonTitle", { name: service.name })}
        >
          <pre className="max-h-[65vh] overflow-auto rounded-2xl bg-slate-950 p-4 text-xs text-slate-100">
            {serverJsonPretty}
          </pre>
        </Modal>
      ) : null}
    </>
  );
}
