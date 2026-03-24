import { Button, Modal, Radio } from "antd";
import McpMarketToolbar from "./McpMarketToolbar";
import McpMarketCardList from "./McpMarketCardList";
import McpMarketDetailModal from "./McpMarketDetailModal";
import type { MarketMcpCard, MarketQuickAddOption } from "@/types/mcpTools";

interface Props {
  marketSearchValue: string;
  selectedMarketService: MarketMcpCard | null;
  filteredMarketServices: MarketMcpCard[];
  marketLoading: boolean;
  marketPage: number;
  hasPrevMarketPage: boolean;
  hasNextMarketPage: boolean;
  marketVersion: string;
  marketUpdatedSince: string;
  marketIncludeDeleted: boolean;
  quickAddPickerVisible: boolean;
  quickAddCandidateService: MarketMcpCard | null;
  quickAddOptions: MarketQuickAddOption[];
  selectedQuickAddOptionKey: string;
  quickAddSubmitting: boolean;
  setMarketSearchValue: (value: string) => void;
  setSelectedMarketService: (service: MarketMcpCard | null) => void;
  setMarketVersion: (value: string) => void;
  setMarketUpdatedSince: (value: string) => void;
  setMarketIncludeDeleted: (value: boolean) => void;
  setSelectedQuickAddOptionKey: (value: string) => void;
  handleMarketPrevPage: () => void;
  handleMarketNextPage: () => void;
  handleQuickAddFromMarket: (service: MarketMcpCard) => void;
  handleCloseQuickAddPicker: () => void;
  handleConfirmQuickAddOption: () => Promise<void>;
  t: (key: string, params?: Record<string, unknown>) => string;
}

export default function AddMcpServiceMarketSection({
  marketSearchValue,
  selectedMarketService,
  filteredMarketServices,
  marketLoading,
  marketPage,
  hasPrevMarketPage,
  hasNextMarketPage,
  marketVersion,
  marketUpdatedSince,
  marketIncludeDeleted,
  quickAddPickerVisible,
  quickAddCandidateService,
  quickAddOptions,
  selectedQuickAddOptionKey,
  quickAddSubmitting,
  setMarketSearchValue,
  setSelectedMarketService,
  setMarketVersion,
  setMarketUpdatedSince,
  setMarketIncludeDeleted,
  setSelectedQuickAddOptionKey,
  handleMarketPrevPage,
  handleMarketNextPage,
  handleQuickAddFromMarket,
  handleCloseQuickAddPicker,
  handleConfirmQuickAddOption,
  t,
}: Props) {
  return (
    <>
      <div className="px-6 py-5 space-y-5">
        <McpMarketToolbar
          marketSearchValue={marketSearchValue}
          marketPage={marketPage}
          resultCount={filteredMarketServices.length}
          marketVersion={marketVersion}
          marketUpdatedSince={marketUpdatedSince}
          marketIncludeDeleted={marketIncludeDeleted}
          onMarketSearchChange={setMarketSearchValue}
          onMarketVersionChange={setMarketVersion}
          onMarketUpdatedSinceChange={setMarketUpdatedSince}
          onMarketIncludeDeletedChange={setMarketIncludeDeleted}
          t={t}
        />

        <McpMarketCardList
          marketLoading={marketLoading}
          services={filteredMarketServices}
          hasPrevMarketPage={hasPrevMarketPage}
          hasNextMarketPage={hasNextMarketPage}
          onPrevMarketPage={handleMarketPrevPage}
          onNextMarketPage={handleMarketNextPage}
          onSelectMarketService={setSelectedMarketService}
          onQuickAddFromMarket={handleQuickAddFromMarket}
          t={t}
        />
      </div>

      {selectedMarketService ? (
        <McpMarketDetailModal
          service={selectedMarketService}
          t={t}
          onClose={() => setSelectedMarketService(null)}
          onQuickAddFromMarket={handleQuickAddFromMarket}
        />
      ) : null}

      <Modal
        open={quickAddPickerVisible}
        onCancel={handleCloseQuickAddPicker}
        footer={null}
        title={t("mcpTools.market.quickAddPicker.title")}
        centered
        destroyOnClose
      >
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            {t("mcpTools.market.quickAddPicker.description", {
              name: quickAddCandidateService?.name || "-",
            })}
          </p>

          <Radio.Group
            value={selectedQuickAddOptionKey}
            onChange={(event) => setSelectedQuickAddOptionKey(String(event.target.value || ""))}
            className="flex w-full flex-col gap-2"
          >
            {quickAddOptions.map((option) => {
              const sourceLabel =
                option.sourceType === "remote"
                  ? t("mcpTools.market.quickAddPicker.sourceRemote")
                  : t("mcpTools.market.quickAddPicker.sourcePackage");

              return (
                <Radio
                  key={option.key}
                  value={option.key}
                  className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2"
                >
                  <div className="space-y-1">
                    <p className="text-xs text-slate-500">{sourceLabel}</p>
                    <p className="text-sm text-slate-800 break-all">{option.sourceLabel}</p>
                  </div>
                </Radio>
              );
            })}
          </Radio.Group>

          <div className="flex justify-end gap-2">
            <Button className="rounded-full" onClick={handleCloseQuickAddPicker}>
              {t("common.cancel")}
            </Button>
            <Button
              type="primary"
              className="rounded-full"
              loading={quickAddSubmitting}
              disabled={!selectedQuickAddOptionKey}
              onClick={() => {
                void handleConfirmQuickAddOption();
              }}
            >
              {t("mcpTools.market.quickAddPicker.confirm")}
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
