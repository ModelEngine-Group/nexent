// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Fragment, useMemo, useRef, type ReactNode } from "react";
import { Drawer, Input, Select } from "antd";
import { Check, ChevronDown, RefreshCw, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import { StandardCloseButton } from "@/components/common/StandardCloseButton";
import { cn } from "@/lib/utils";
import type {
  ResourcePickerTab,
  ResourceRowItem,
  SelectedItem,
  TagOption,
} from "./types";

/** Square checkbox matching the design spec (16x16, radius 2, blue when checked). */
export function CheckMark({
  checked,
  onToggle,
  ariaLabel,
}: {
  checked: boolean;
  onToggle?: () => void;
  ariaLabel?: string;
}) {
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      aria-pressed={checked}
      onClick={onToggle}
      className={cn(
        "flex h-4 w-4 shrink-0 cursor-pointer items-center justify-center rounded-[2px] border",
        checked
          ? "border-[#0067D1] bg-[#0067D1] text-white"
          : "border-[#C9C9C9] bg-white"
      )}
    >
      {checked && <Check size={11} strokeWidth={3} />}
    </button>
  );
}

/** Search input plus optional tag dropdown (hidden when no tag options provided). */
export function SearchRow({
  placeholder,
  tagOptions,
  onSearch,
  onTagChange,
}: {
  placeholder: string;
  tagOptions?: TagOption[];
  onSearch?: (keyword: string) => void;
  onTagChange?: (value?: string) => void;
}) {
  const { t } = useTranslation("common");
  return (
    <div data-picker-part="search" className="flex shrink-0 items-center gap-4">
      <Input
        allowClear
        placeholder={placeholder}
        onChange={(e) => onSearch?.(e.target.value)}
        suffix={<Search size={14} className="text-[#999]" />}
        className={cn(
          "[&::placeholder]:!text-[#B8B8B8]",
          !tagOptions ? "flex-1" : "h-8 flex-1"
        )}
        classNames={{
          input:
            "!border-0 !bg-transparent !p-0 !outline-none !shadow-none !placeholder:text-[#B8B8B8]",
        }}
        styles={{
          root: {
            width: "100%",
            height: 32,
            padding: "5px 12px",
            gap: 8,
            boxSizing: "border-box",
            borderColor: "rgba(217, 217, 217, 1)",
          },
        }}
        style={!tagOptions ? undefined : { flex: 1 }}
        variant="outlined"
      />
      {tagOptions && (
        <Select
          allowClear
          placeholder={t("resourcePicker.tags")}
          options={tagOptions}
          onChange={onTagChange}
          suffixIcon={<ChevronDown size={12} className="text-[#666]" />}
          className={cn(
            "w-[222px] shrink-0",
            "[&_.ant-select-selector]:!h-8 [&_.ant-select-selector]:!px-3 [&_.ant-select-selector]:!py-[5px] [&_.ant-select-selector]:!border-[rgba(201,201,201,1)]"
          )}
          styles={{
            root: {
              width: 222,
              height: 32,
              boxSizing: "border-box",
            },
          }}
          variant="outlined"
        />
      )}
    </div>
  );
}

/** Selected chips row shown below the search row. */
export function SelectedChips({
  items,
  onRemove,
  trailing,
}: {
  items: SelectedItem[];
  onRemove?: (id: string) => void;
  trailing?: ReactNode;
}) {
  const { t } = useTranslation("common");
  if (items.length === 0 && !trailing) return null;
  return (
    <div
      data-picker-part="chips"
      className="flex shrink-0 flex-wrap items-center gap-2"
    >
      {items.map((item) => (
        <span
          key={item.id}
          className="flex h-7 items-center gap-1 rounded-[4px] bg-[rgba(25,25,25,0.04)] px-3 text-[12px] leading-[20px] text-[#191919]"
          style={{ fontFamily: '"HarmonyHeiTi", sans-serif' }}
        >
          {item.label}
          <button
            type="button"
            aria-label={t("resourcePicker.remove")}
            onClick={() => onRemove?.(item.id)}
            className="ml-0.5 cursor-pointer border-0 bg-transparent p-0 text-[#666]"
          >
            ✕
          </button>
        </span>
      ))}
      {trailing}
    </div>
  );
}

/** List section header: title on the left, tools (select-all / refresh) on the right. */
export function ListHeader({
  title,
  onSelectAll,
  allSelected,
  onRefresh,
  extra,
}: {
  title: string;
  onSelectAll?: (checked: boolean) => void;
  allSelected?: boolean;
  onRefresh?: () => void;
  extra?: ReactNode;
}) {
  const { t } = useTranslation("common");
  return (
    <div className="flex h-6 shrink-0 items-center justify-between">
      <span className="text-[16px] font-medium leading-[24px] text-[#191919]">
        {title}
      </span>
      <div className="flex items-center gap-4 text-[14px] leading-[22px]">
        {extra}
        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            className="flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-[#2673E5]"
          >
            <RefreshCw size={14} />
            {t("resourcePicker.refresh", "刷新")}
          </button>
        )}
        {onSelectAll && (
          <span className="flex items-center gap-1.5 text-[#191919]">
            <CheckMark
              checked={allSelected ?? false}
              onToggle={() => onSelectAll(!allSelected)}
              ariaLabel={t("resourcePicker.selectAll", "全选")}
            />
            {t("resourcePicker.selectAll", "全选")}
          </span>
        )}
      </div>
    </div>
  );
}

/** List row shared by the "add skill" and "add tool" drawers (64px). */
export function ResourceRow({
  item,
  selected,
  onToggle,
}: {
  item: ResourceRowItem;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      className={cn(
        "flex shrink-0 items-center gap-3 rounded-[2px] px-5 py-[9px]",
        selected ? "bg-[#E6F2FD]" : "bg-transparent"
      )}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "text-[14px] leading-[20px]",
              selected
                ? "font-medium text-[#0067D1]"
                : item.link
                  ? "text-[#2673E5]"
                  : "font-medium text-[#191919]"
            )}
          >
            {item.name}
          </span>
          {item.tags.map((tag) => (
            <span
              key={tag}
              className="h-5 rounded-[2px] bg-[#F5F5F5] px-2 text-[12px] leading-[20px] text-[#393939]"
            >
              {tag}
            </span>
          ))}
        </div>
        <p className="truncate text-[14px] leading-[20px] text-[#737373]">
          {item.description}
        </p>
      </div>
      <CheckMark checked={selected} onToggle={onToggle} />
    </div>
  );
}

/** Tab strip used by the agent / skill / tool drawers. */
export function ResourceTabs({
  tabs,
  activeKey,
  onChange,
}: {
  tabs: ResourcePickerTab[];
  activeKey: string;
  onChange?: (key: string) => void;
}) {
  return (
    <div data-picker-part="tabs" className="flex shrink-0 items-center gap-3">
      {tabs.map((tab, index) => (
        <Fragment key={tab.key}>
          {index > 0 && <span className="h-[14px] w-px bg-[#D9D9D9]" />}
          <button
            type="button"
            onClick={() => onChange?.(tab.key)}
            className={cn(
              "cursor-pointer border-0 bg-transparent p-0 text-[14px] leading-[20px]",
              activeKey === tab.key ? "text-[#2D5BB3]" : "text-[#737373]"
            )}
          >
            {tab.label}
          </button>
        </Fragment>
      ))}
    </div>
  );
}

/** Pagination footer matching the design spec (total, page-size, pager, jump). */
export function ResourcePagination({
  total,
  pageSize = 10,
  current,
  onPageChange,
}: {
  total: number;
  pageSize?: number;
  current: number;
  onPageChange: (page: number) => void;
}) {
  const { t } = useTranslation("common");
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const safeCurrent = Math.min(Math.max(1, current), pageCount);

  const pages = useMemo(() => {
    const count = pageCount;
    if (count <= 7) {
      return Array.from({ length: count }, (_, i) => i + 1);
    }
    // Show first five, an ellipsis, then the last page.
    return [1, 2, 3, 4, 5, -1, count];
  }, [pageCount]);

  const goTo = (page: number) => {
    const next = Math.min(Math.max(1, page), pageCount);
    if (next !== safeCurrent) onPageChange(next);
  };

  const jumpInputRef = useRef<HTMLInputElement>(null);
  const jump = () => {
    const value = Number(jumpInputRef.current?.value);
    if (Number.isInteger(value)) goTo(value);
  };

  return (
    <div
      data-picker-part="pagination"
      className="flex h-8 shrink-0 items-center gap-4"
    >
      <span className="text-[14px] leading-[22px] text-[#191919]">
        {t("resourcePicker.total", "总计")}: {total}
      </span>
      <Select
        value={pageSize}
        options={[10, 20, 50].map((size) => ({
          value: size,
          label: `${size} ${t("resourcePicker.perPage", "条/页")}`,
        }))}
        suffixIcon={<ChevronDown size={12} className="text-[#666]" />}
        className="w-[140px]"
        styles={{ root: { width: 140 } }}
        variant="outlined"
      />
      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-label={t("resourcePicker.previousPage")}
          onClick={() => goTo(safeCurrent - 1)}
          className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-[4px] border-0 bg-transparent text-[#666]"
        >
          ‹
        </button>
        {pages.map((page) =>
          page === -1 ? (
            <span
              key="ellipsis"
              className="flex h-8 items-center justify-center px-1 text-[14px] tracking-[2px] text-[#666]"
            >
              ···
            </span>
          ) : (
            <button
              key={page}
              type="button"
              onClick={() => goTo(page)}
              className={cn(
                "flex h-8 w-8 cursor-pointer items-center justify-center rounded-[4px] border-0 text-[14px]",
                page === safeCurrent
                  ? "bg-[#E6F2FD] text-[#0067D1]"
                  : "bg-transparent text-[#191919]"
              )}
            >
              {page}
            </button>
          )
        )}
        <button
          type="button"
          aria-label={t("resourcePicker.nextPage")}
          onClick={() => goTo(safeCurrent + 1)}
          className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-[4px] border-0 bg-transparent text-[#666]"
        >
          ›
        </button>
      </div>
      <div className="flex h-8 w-[96px] items-center rounded-[4px] border border-[#D9D9D9] bg-white">
        <input
          ref={jumpInputRef}
          key={safeCurrent}
          type="text"
          defaultValue={safeCurrent}
          onKeyDown={(e) => {
            if (e.key === "Enter") jump();
          }}
          className="h-full min-w-0 flex-1 border-0 bg-transparent text-center text-[14px] leading-[22px] text-[#191919] outline-none"
        />
        <span className="h-full w-px shrink-0 bg-[#D9D9D9]" />
        <button
          type="button"
          onClick={jump}
          className="flex h-full flex-1 cursor-pointer items-center justify-center border-0 bg-transparent p-0 text-[14px] leading-[22px] text-[#191919]"
        >
          {t("resourcePicker.jump", "跳转")}
        </button>
      </div>
    </div>
  );
}

export interface AddResourceDrawerProps {
  /** Optional presentation overrides; the default resource drawers retain their layout. */
  width?: number;
  bodyClassName?: string;
  open: boolean;
  title: ReactNode;
  searchPlaceholder: string;
  selected: SelectedItem[];
  tagOptions?: TagOption[];
  listTitle: string;
  tabs?: ResourcePickerTab[];
  activeTab?: string;
  showConfirm?: boolean;
  total: number;
  page?: number;
  onPageChange?: (page: number) => void;
  onClose: () => void;
  onConfirm?: () => void;
  confirmLoading?: boolean;
  onRemoveSelected?: (id: string) => void;
  onSearch?: (keyword: string) => void;
  onTagChange?: (value?: string) => void;
  onTabChange?: (key: string) => void;
  onSelectAll?: (checked: boolean) => void;
  onRefresh?: () => void;
  allSelected?: boolean;
  selectedTrailing?: ReactNode;
  children: ReactNode;
  /** Use the same drawer shell with an existing resource controller's filters. */
  searchContent?: ReactNode;
  showSelection?: boolean;
  showListHeader?: boolean;
  /** Extra action rendered to the left of the refresh button in the list header. */
  listHeaderExtra?: ReactNode;
  showPagination?: boolean;
}

/**
 * Shared skeleton for the five "add resource" right-side drawers.
 * Header, search row, selected chips, list header, tabs, pagination and footer
 * buttons are identical across the five designs; only the list body differs.
 */
export function AddResourceDrawer({
  width = 760,
  bodyClassName,
  open,
  title,
  searchPlaceholder,
  selected,
  tagOptions,
  listTitle,
  tabs,
  activeTab,
  showConfirm = true,
  total,
  page = 1,
  onPageChange,
  onClose,
  onConfirm,
  confirmLoading = false,
  onRemoveSelected,
  onSearch,
  onTagChange,
  onTabChange,
  onSelectAll,
  onRefresh,
  allSelected,
  selectedTrailing,
  children,
  searchContent,
  showSelection = true,
  showListHeader = true,
  listHeaderExtra,
  showPagination = true,
}: AddResourceDrawerProps) {
  const { t } = useTranslation("common");
  const handleClose = () => {
    if (!confirmLoading) onClose();
  };

  return (
    <Drawer
      open={open}
      placement="right"
      size={width}
      classNames={{ body: bodyClassName }}
      onClose={handleClose}
      closable={false}
      mask={{ closable: false }}
      styles={{
        body: {
          padding: 24,
          display: "flex",
          flexDirection: "column",
          gap: 16,
          overflow: "hidden",
          background: "#fff",
        },
      }}
    >
      <div
        data-picker-part="header"
        className="flex h-[28px] shrink-0 items-center justify-between"
      >
        <span
          className={cn(
            "overflow-hidden whitespace-nowrap text-[20px] font-medium leading-[28px] text-[#191919]",
            typeof title === "string" ? "max-w-[300px]" : "min-w-0 flex-1 pr-4"
          )}
        >
          {title}
        </span>
        <StandardCloseButton
          ariaLabel={t("resourcePicker.close", "关闭")}
          onClick={handleClose}
        />
      </div>

      {searchContent !== undefined ? (
        searchContent
      ) : (
        <SearchRow
          placeholder={searchPlaceholder}
          tagOptions={tagOptions}
          onSearch={onSearch}
          onTagChange={onTagChange}
        />
      )}

      {showSelection && (
        <div data-picker-part="selection" className="contents">
          <div className="shrink-0 text-[14px] leading-[20px] text-[#999999]">
            {t("resourcePicker.selected", "已选")}
          </div>
          <SelectedChips
            items={selected}
            onRemove={onRemoveSelected}
            trailing={selectedTrailing}
          />
        </div>
      )}

      <div data-picker-part="list-heading" className="contents">
        {showListHeader && (
          <ListHeader
            title={listTitle}
            onSelectAll={onSelectAll}
            allSelected={allSelected}
            onRefresh={onRefresh}
            extra={listHeaderExtra}
          />
        )}

        {tabs && activeTab !== undefined && (
          <ResourceTabs
            tabs={tabs}
            activeKey={activeTab}
            onChange={onTabChange}
          />
        )}
      </div>

      <div
        data-picker-part="list-content"
        className="min-h-0 flex-1 overflow-y-auto"
      >
        {children}
      </div>

      {showPagination && (
        <ResourcePagination
          total={total}
          current={page}
          onPageChange={onPageChange ?? (() => {})}
        />
      )}

      <div
        data-picker-part="footer"
        className="flex shrink-0 justify-end gap-3"
      >
        <button
          type="button"
          onClick={handleClose}
          disabled={confirmLoading}
          className="h-8 w-[89px] cursor-pointer rounded-[2px] border border-[#C9C9C9] bg-white text-[14px] leading-[22px] text-[#191919]"
        >
          {t("resourcePicker.close", "关闭")}
        </button>
        {showConfirm && (
          <button
            type="button"
            onClick={onConfirm}
            disabled={confirmLoading}
            aria-busy={confirmLoading}
            className="inline-flex h-8 w-[89px] cursor-pointer items-center justify-center gap-2 rounded-[2px] border-0 bg-[#1476FF] text-[14px] leading-[22px] text-white"
          >
            {confirmLoading && (
              <RefreshCw aria-hidden size={14} className="animate-spin" />
            )}
            {t("resourcePicker.confirm", "确认")}
          </button>
        )}
      </div>
    </Drawer>
  );
}
