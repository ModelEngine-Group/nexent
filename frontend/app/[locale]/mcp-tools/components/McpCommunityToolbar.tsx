import { Input, Select } from "antd";
import { useTranslation } from "react-i18next";
import { MCP_TRANSPORT_TYPE } from "@/const/mcpTools";
import type { McpTagStat, McpTransportFilter } from "@/types/mcpTools";
import { FILTER_ALL } from "@/types/mcpTools";

interface McpCommunityToolbarProps {
  search: string;
  transport: McpTransportFilter;
  tag: string;
  tagStats: McpTagStat[];
  page: number;
  resultCount: number;
  onSearchChange: (value: string) => void;
  onTransportChange: (value: McpTransportFilter) => void;
  onTagChange: (value: string) => void;
}

/**
 * Community-browser toolbar. Search input takes ~2/3 of the row, the two
 * filter selects share the remaining space and stay narrow on desktop.
 */
export default function McpCommunityToolbar({
  search,
  transport,
  tag,
  tagStats,
  page,
  resultCount,
  onSearchChange,
  onTransportChange,
  onTagChange,
}: McpCommunityToolbarProps) {
  const { t } = useTranslation("common");

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
        <Input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder={t("mcpTools.community.searchPlaceholder")}
          size="large"
          allowClear
          className="w-full rounded-md lg:basis-2/3"
        />
        <div className="flex flex-wrap gap-2 lg:basis-1/3">
          <Select
            size="large"
            value={transport}
            onChange={onTransportChange}
            className="min-w-[120px] flex-1"
            options={[
              {
                value: FILTER_ALL,
                label: t("mcpTools.page.transportFilter.all"),
              },
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
            className="min-w-[140px] flex-1"
            options={[
              { value: FILTER_ALL, label: t("mcpTools.page.tagFilter.all") },
              ...tagStats.map((item) => ({
                value: item.tag,
                label: `${item.tag} (${item.count})`,
              })),
            ]}
          />
        </div>
      </div>
      <span className="text-xs text-slate-400">
        {t("mcpTools.community.pageResult", { page, count: resultCount })}
      </span>
    </div>
  );
}
