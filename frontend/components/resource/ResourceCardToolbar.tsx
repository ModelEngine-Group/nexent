"use client";

import { Input } from "antd";
import { Search } from "lucide-react";
import type { ReactNode } from "react";

export interface ResourceFilterOption {
  key: string;
  label: ReactNode;
  count?: number;
}

interface ResourceCardToolbarProps {
  search: string;
  searchPlaceholder?: string;
  onSearchChange: (value: string) => void;
  filters?: ResourceFilterOption[];
  activeFilter?: string;
  onFilterChange?: (key: string) => void;
}

export default function ResourceCardToolbar({
  search,
  searchPlaceholder,
  onSearchChange,
  filters = [],
  activeFilter,
  onFilterChange,
}: ResourceCardToolbarProps) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <Input
        value={search}
        onChange={(event) => onSearchChange(event.target.value)}
        allowClear
        prefix={<Search size={16} className="text-slate-400" />}
        placeholder={searchPlaceholder}
        className="h-10 w-full sm:max-w-md"
      />
      {filters.length > 0 ? (
        <div className="flex items-center gap-5 border-b border-slate-200 text-sm">
          {filters.map((filter) => (
            <button
              key={filter.key}
              type="button"
              onClick={() => onFilterChange?.(filter.key)}
              className={`border-b-2 px-1 pb-2 font-medium transition-colors ${
                activeFilter === filter.key
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              {filter.label}
              {filter.count !== undefined ? (
                <span className="ml-1 text-xs text-slate-400">
                  {filter.count}
                </span>
              ) : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
