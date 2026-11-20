// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import RepositoryDisplayControls from "@/app/resource-space/components/RepositoryDisplayControls";
import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";
import { Input, Select } from "antd";
import { Search } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

interface FilterTab {
  value: string;
  label: string;
  count: number;
}

interface McpToolsSearchFilterBarProps {
  search: string;
  searchPlaceholder?: string;
  status?: string;
  statusOptions?: Array<{ value: string; label: string }>;
  actions?: ReactNode;
  searchActions?: ReactNode;
  filterActions?: ReactNode;
  onSearchChange: (value: string) => void;
  onStatusChange?: (value: string) => void;
  filterTabs?: FilterTab[];
  activeFilterTab?: string;
  onFilterTabChange?: (value: string) => void;
}

export default function McpToolsSearchFilterBar({
  search,
  searchPlaceholder,
  status,
  statusOptions,
  actions,
  searchActions,
  filterActions,
  onSearchChange,
  onStatusChange,
  filterTabs,
  activeFilterTab,
  onFilterTabChange,
}: McpToolsSearchFilterBarProps) {
  const { t } = useTranslation("common");
  const presentation = useRepositoryPresentation();
  const measuredMine =
    presentation?.resourceType === "mcp" &&
    presentation.query?.get("view") === "mine";
  const measuredRepository =
    presentation?.resourceType === "mcp" &&
    presentation.query?.get("view") !== "mine";

  const renderTab = (
    item: { value: string; label: string; count: number },
    selected: boolean,
    onClick: () => void
  ) => (
    <button
      key={item.value}
      type="button"
      onClick={onClick}
      className={`rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors ${
        selected
          ? "bg-primary text-white"
          : "bg-slate-100 text-slate-700 hover:bg-slate-200"
      }`}
    >
      <span>{item.label}</span>
      <span className="ml-1 text-xs opacity-80">{item.count}</span>
    </button>
  );

  const filterTabsContent = filterTabs?.length
    ? filterTabs.map((item) =>
        renderTab(item, activeFilterTab === item.value, () =>
          onFilterTabChange?.(item.value)
        )
      )
    : null;

  const tabsContent =
    filterTabsContent || filterActions ? (
      <div className="mt-3 flex items-center gap-2 border-t border-slate-100 pt-3">
        <div className="flex flex-wrap gap-2">{filterTabsContent}</div>
        {filterActions ? (
          <div className="ml-auto shrink-0">{filterActions}</div>
        ) : null}
      </div>
    ) : null;

  return (
    <div>
      <div
        className={
          measuredMine
            ? "flex shrink-0 flex-wrap items-center gap-2"
            : measuredRepository
              ? "flex shrink-0 flex-wrap items-center gap-2"
              : "flex flex-row items-center gap-3 overflow-x-auto"
        }
      >
        <div
          className={
            measuredMine
              ? "flex min-w-[192px] flex-1 items-center gap-2"
              : measuredRepository
                ? "contents"
                : "flex min-w-[240px] flex-1 items-center gap-3"
          }
        >
          <Input
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={
              searchPlaceholder || t("mcpTools.page.searchNameTagPlaceholder")
            }
            allowClear
            prefix={
              <Search
                className={
                  measuredRepository
                    ? "size-4 text-[#777777]"
                    : "h-4 w-4 text-slate-400"
                }
              />
            }
            className={
              measuredRepository
                ? "repository-search-field h-8 gap-1 rounded border-[#C9C9C9] bg-white px-3 py-[5px] text-sm leading-[22px] [&_input::placeholder]:text-[#AEAEAE]"
                : measuredMine
                  ? "h-8 !min-w-[80px] max-w-[800px] flex-[1_1_320px] rounded-lg border-slate-200 bg-slate-50/60"
                  : "h-8 min-w-0 flex-1 rounded-lg border-slate-200 bg-slate-50/60"
            }
          />
          {searchActions ? (
            <div
              className={
                measuredMine
                  ? "min-w-12 max-w-[240px] flex-[1_1_240px]"
                  : measuredRepository
                    ? "max-w-full shrink-0"
                    : "shrink-0"
              }
            >
              {searchActions}
            </div>
          ) : null}
          {statusOptions && onStatusChange ? (
            <Select
              value={status}
              onChange={onStatusChange}
              className="h-8 w-full min-w-[150px]"
              popupMatchSelectWidth={false}
              options={statusOptions}
            />
          ) : null}
        </div>
        {measuredMine ? (
          <div className="ml-auto flex shrink-0 items-center gap-2">
            {actions}
            <RepositoryDisplayControls showSort={false} />
          </div>
        ) : (
          <>
            {actions ? (
              <div className="flex shrink-0 flex-nowrap gap-2">{actions}</div>
            ) : null}
            <RepositoryDisplayControls showSort={false} />
          </>
        )}
      </div>
      {tabsContent}
    </div>
  );
}
