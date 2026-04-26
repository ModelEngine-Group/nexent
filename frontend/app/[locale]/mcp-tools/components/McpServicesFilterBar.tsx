import { Select } from "antd";
import { useTranslation } from "react-i18next";
import { MCP_TAB, MCP_TRANSPORT_TYPE } from "@/const/mcpTools";
import type {
  McpSourceFilter,
  McpTagStat,
  McpTransportFilter,
} from "@/types/mcpTools";
import { FILTER_ALL } from "@/types/mcpTools";

interface McpServicesFilterBarProps {
  source: McpSourceFilter;
  transport: McpTransportFilter;
  tag: string;
  tagStats: McpTagStat[];
  onSourceChange: (value: McpSourceFilter) => void;
  onTransportChange: (value: McpTransportFilter) => void;
  onTagChange: (value: string) => void;
}

/**
 * Compact 3-pill filter bar designed to sit inline with the search input on
 * desktop. Each select is fixed-width so the whole row stays balanced
 * regardless of locale length.
 */
export default function McpServicesFilterBar({
  source,
  transport,
  tag,
  tagStats,
  onSourceChange,
  onTransportChange,
  onTagChange,
}: McpServicesFilterBarProps) {
  const { t } = useTranslation("common");

  return (
    <div className="flex flex-wrap gap-2">
      <Select
        size="large"
        value={source}
        onChange={onSourceChange}
        className="min-w-[140px] flex-1 lg:flex-none lg:w-36"
        options={[
          { value: FILTER_ALL, label: t("mcpTools.page.sourceFilter.all") },
          { value: MCP_TAB.LOCAL, label: t("mcpTools.source.local") },
          {
            value: MCP_TAB.MCP_REGISTRY,
            label: t("mcpTools.source.registry"),
          },
          { value: MCP_TAB.COMMUNITY, label: t("mcpTools.source.community") },
        ]}
      />
      <Select
        size="large"
        value={transport}
        onChange={onTransportChange}
        className="min-w-[140px] flex-1 lg:flex-none lg:w-36"
        options={[
          { value: FILTER_ALL, label: t("mcpTools.page.transportFilter.all") },
          {
            value: MCP_TRANSPORT_TYPE.HTTP,
            label: t("mcpTools.serverType.http"),
          },
          {
            value: MCP_TRANSPORT_TYPE.SSE,
            label: t("mcpTools.serverType.sse"),
          },
          {
            value: MCP_TRANSPORT_TYPE.CONTAINER,
            label: t("mcpTools.serverType.container"),
          },
        ]}
      />
      <Select
        size="large"
        value={tag}
        onChange={onTagChange}
        className="min-w-[140px] flex-1 lg:flex-none lg:w-40"
        options={[
          { value: FILTER_ALL, label: t("mcpTools.page.tagFilter.all") },
          ...tagStats.map((item) => ({
            value: item.tag,
            label: `${item.tag} (${item.count})`,
          })),
        ]}
      />
    </div>
  );
}
