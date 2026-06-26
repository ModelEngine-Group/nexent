import { useState } from "react";
import type { CommunityMcpCard } from "@/types/mcpTools";
import { useMcpCommunityBrowser } from "@/hooks/mcpTools/useMcpCommunityBrowser";
import { useMcpCommunityQuickAdd } from "@/hooks/mcpTools/useMcpCommunityQuickAdd";
import McpCommunityToolbar from "./McpCommunityToolbar";
import McpCommunityCardList from "./McpCommunityCardList";
import McpCommunityDetailModal from "./McpCommunityDetailModal";
import CommunityQuickAddModal from "./CommunityQuickAddModal";

interface AddMcpServiceCommunitySectionProps {
  active: boolean;
  onAdded: () => void;
}

export default function AddMcpServiceCommunitySection({
  active,
  onAdded,
}: AddMcpServiceCommunitySectionProps) {
  const [selected, setSelected] = useState<CommunityMcpCard | null>(null);
  const browser = useMcpCommunityBrowser(active);
  const quickAdd = useMcpCommunityQuickAdd({ onSuccess: onAdded });

  if (!active) return null;

  return (
    <>
      <div className="space-y-5 px-6 py-5">
        <McpCommunityToolbar
          search={browser.filters.search}
          transport={browser.filters.transport}
          tag={browser.filters.tag}
          tagStats={browser.tagStats}
          page={browser.page}
          resultCount={browser.services.length}
          onSearchChange={(value) => browser.updateFilter("search", value)}
          onTransportChange={(value) =>
            browser.updateFilter("transport", value)
          }
          onTagChange={(value) => browser.updateFilter("tag", value)}
        />

        <McpCommunityCardList
          loading={browser.loading}
          services={browser.services}
          hasPrevPage={browser.hasPrevPage}
          hasNextPage={browser.hasNextPage}
          onPrevPage={browser.prevPage}
          onNextPage={browser.nextPage}
          onSelect={setSelected}
          onQuickAdd={quickAdd.open}
        />
      </div>

      {selected ? (
        <McpCommunityDetailModal
          service={selected}
          onClose={() => setSelected(null)}
          onQuickAdd={quickAdd.open}
        />
      ) : null}

      {quickAdd.visible ? <CommunityQuickAddModal controller={quickAdd} /> : null}
    </>
  );
}
