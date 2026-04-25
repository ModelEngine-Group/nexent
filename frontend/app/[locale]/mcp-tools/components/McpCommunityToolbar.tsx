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
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <Input
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder={t("mcpTools.community.searchPlaceholder")}
          size="large"
          className="w-full rounded-2xl"
        />
        <Select
          size="large"
          value={transport}
          onChange={onTransportChange}
          className="w-full"
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
          className="w-full"
          options={[
            { value: FILTER_ALL, label: t("mcpTools.page.tagFilter.all") },
            ...tagStats.map((item) => ({
              value: item.tag,
              label: `${item.tag} (${item.count})`,
            })),
          ]}
        />
      </div>
      <div className="flex items-center gap-3">
        <div className="whitespace-nowrap rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
          {t("mcpTools.community.pageResult", { page, count: resultCount })}
        </div>
      </div>
    </div>
  );
}
