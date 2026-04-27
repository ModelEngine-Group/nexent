import { Select } from "antd";
import { useTranslation } from "react-i18next";
import { FILTER_ALL, McpSource, McpTransportType } from "@/const/mcpTools";
import type {
  McpSourceFilter,
  McpTagStat,
  McpTransportFilter,
} from "@/types/mcpTools";

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
          { value: McpSource.LOCAL, label: t("mcpTools.source.local") },
          {
            value: McpSource.REGISTRY,
            label: t("mcpTools.source.registry"),
          },
          { value: McpSource.COMMUNITY, label: t("mcpTools.source.community") },
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
            value: McpTransportType.HTTP,
            label: t("mcpTools.serverType.http"),
          },
          {
            value: McpTransportType.SSE,
            label: t("mcpTools.serverType.sse"),
          },
          {
            value: McpTransportType.CONTAINER,
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
