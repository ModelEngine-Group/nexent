import McpMarketToolbar from "./McpMarketToolbar";
import McpMarketCardList from "./McpMarketCardList";
import McpMarketDetailModal from "./McpMarketDetailModal";
import type { AddMcpMarketActions, AddMcpMarketState } from "@/types/mcpTools";

interface Props {
  state: AddMcpMarketState;
  actions: AddMcpMarketActions;
  t: (key: string, params?: Record<string, unknown>) => string;
}

export default function AddMcpServiceMarketSection({ state, actions, t }: Props) {
  const toolbarState = {
    marketSearchValue: state.marketSearchValue,
    marketLoading: state.marketLoading,
    marketPage: state.marketPage,
    resultCount: state.filteredMarketServices.length,
    marketVersion: state.marketVersion,
    marketUpdatedSince: state.marketUpdatedSince,
    marketIncludeDeleted: state.marketIncludeDeleted,
  };

  const toolbarActions = {
    onMarketSearchChange: actions.onMarketSearchChange,
    onRefreshMarket: actions.onRefreshMarket,
    onMarketVersionChange: actions.onMarketVersionChange,
    onMarketUpdatedSinceChange: actions.onMarketUpdatedSinceChange,
    onMarketIncludeDeletedChange: actions.onMarketIncludeDeletedChange,
  };

  return (
    <>
      <div className="px-6 py-5 space-y-5">
        <McpMarketToolbar state={toolbarState} actions={toolbarActions} t={t} />

        <McpMarketCardList
          marketLoading={state.marketLoading}
          services={state.filteredMarketServices}
          hasPrevMarketPage={state.hasPrevMarketPage}
          hasNextMarketPage={state.hasNextMarketPage}
          onPrevMarketPage={actions.onPrevMarketPage}
          onNextMarketPage={actions.onNextMarketPage}
          onSelectMarketService={actions.onSelectMarketService}
          onQuickAddFromMarket={actions.onQuickAddFromMarket}
          t={t}
        />
      </div>

      {state.selectedMarketService ? (
        <McpMarketDetailModal
          service={state.selectedMarketService}
          t={t}
          onClose={() => actions.onSelectMarketService(null)}
          onQuickAddFromMarket={actions.onQuickAddFromMarket}
        />
      ) : null}
    </>
  );
}
