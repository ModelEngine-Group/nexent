import { Input } from "antd";

interface Props {
  communitySearchValue: string;
  communityPage: number;
  resultCount: number;
  onCommunitySearchChange: (value: string) => void;
  t: (key: string, params?: Record<string, unknown>) => string;
}

export default function McpCommunityToolbar({
  communitySearchValue,
  communityPage,
  resultCount,
  onCommunitySearchChange,
  t,
}: Props) {
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <Input
          value={communitySearchValue}
          onChange={(event) => onCommunitySearchChange(event.target.value)}
          placeholder={t("mcpTools.community.searchPlaceholder")}
          size="large"
          className="w-full rounded-2xl"
        />
        <div className="whitespace-nowrap rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
          {t("mcpTools.community.pageResult", { page: communityPage, count: resultCount })}
        </div>
      </div>
    </div>
  );
}
