import { Input, Select } from "antd";
import { Search } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { FILTER_ALL, McpDeploymentType } from "@/const/mcpTools";

type DeploymentFilter = McpDeploymentType | typeof FILTER_ALL;

interface McpCategoryStat {
  value: DeploymentFilter;
  label: string;
  count: number;
}

interface McpToolsSearchFilterBarProps {
  search: string;
  deploymentType: DeploymentFilter;
  searchPlaceholder?: string;
  status?: string;
  statusOptions?: Array<{ value: string; label: string }>;
  categoryStats?: McpCategoryStat[];
  actions?: ReactNode;
  onSearchChange: (value: string) => void;
  onDeploymentTypeChange: (value: DeploymentFilter) => void;
  onStatusChange?: (value: string) => void;
}

export default function McpToolsSearchFilterBar({
  search,
  deploymentType,
  searchPlaceholder,
  status,
  statusOptions,
  categoryStats,
  actions,
  onSearchChange,
  onDeploymentTypeChange,
  onStatusChange,
}: McpToolsSearchFilterBarProps) {
  const { t } = useTranslation("common");

  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
        <div className="grid min-w-0 flex-1 gap-3 lg:grid-cols-[minmax(240px,1fr)_auto] lg:items-center">
          <Input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={searchPlaceholder || t("mcpTools.page.searchNameTagPlaceholder")}
            allowClear
            prefix={<Search className="h-4 w-4 text-slate-400" />}
            className="h-10 rounded-lg border-slate-200 bg-slate-50/60"
          />
          {statusOptions && onStatusChange ? (
            <Select
              value={status}
              onChange={onStatusChange}
              className="h-10 w-full min-w-[150px]"
              popupMatchSelectWidth={false}
              options={statusOptions}
            />
          ) : null}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap gap-2 xl:justify-end">{actions}</div> : null}
      </div>
      {categoryStats?.length ? (
        <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
          {categoryStats.map((item) => {
            const selected = deploymentType === item.value;
            return (
              <button
                key={item.value}
                type="button"
                onClick={() => onDeploymentTypeChange(item.value)}
                className={`inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-xs transition ${
                  selected
                    ? "border-emerald-500 bg-emerald-500 font-medium text-white shadow-sm"
                    : "border-slate-200 bg-slate-50 text-slate-600 hover:border-emerald-200 hover:bg-emerald-50 hover:text-emerald-700"
                }`}
              >
                <span>{item.label}</span>
                <span className={`rounded-full px-1.5 text-[11px] ${selected ? "bg-white/20 text-white" : "bg-white text-slate-500"}`}>
                  {item.count}
                </span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
