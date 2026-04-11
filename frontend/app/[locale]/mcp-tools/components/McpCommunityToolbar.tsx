import { Input, Select } from "antd";

interface Props {
  communitySearchValue: string;
  communityTransportTypeFilter: "all" | "http" | "sse" | "container";
  communityTagFilter: string;
  communityTagStats: Array<{ tag: string; count: number }>;
  communityPage: number;
  resultCount: number;
  onCommunitySearchChange: (value: string) => void;
  onCommunityTransportTypeFilterChange: (value: "all" | "http" | "sse" | "container") => void;
  onCommunityTagFilterChange: (value: string) => void;
  t: (key: string, params?: Record<string, unknown>) => string;
}

export default function McpCommunityToolbar({
  communitySearchValue,
  communityTransportTypeFilter,
  communityTagFilter,
  communityTagStats,
  communityPage,
  resultCount,
  onCommunitySearchChange,
  onCommunityTransportTypeFilterChange,
  onCommunityTagFilterChange,
  t,
}: Props) {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <Input
          value={communitySearchValue}
          onChange={(event) => onCommunitySearchChange(event.target.value)}
          placeholder={t("mcpTools.community.searchPlaceholder")}
          size="large"
          className="w-full rounded-2xl"
        />
        <Select
          size="large"
          value={communityTransportTypeFilter}
          onChange={onCommunityTransportTypeFilterChange}
          className="w-full"
          options={[
            { value: "all", label: t("mcpTools.page.transportFilter.all") },
            { value: "http", label: t("mcpTools.serverType.http") },
            { value: "sse", label: t("mcpTools.serverType.sse") },
            { value: "container", label: t("mcpTools.serverType.container") },
          ]}
        />
        <Select
          size="large"
          value={communityTagFilter}
          onChange={onCommunityTagFilterChange}
          className="w-full"
          options={[
            { value: "all", label: t("mcpTools.page.tagFilter.all") },
            ...communityTagStats.map((item) => ({
              value: item.tag,
              label: `${item.tag} (${item.count})`,
            })),
          ]}
        />
      </div>
      <div className="flex items-center gap-3">
        <div className="whitespace-nowrap rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
          {t("mcpTools.community.pageResult", { page: communityPage, count: resultCount })}
        </div>
      </div>
    </div>
  );
}
