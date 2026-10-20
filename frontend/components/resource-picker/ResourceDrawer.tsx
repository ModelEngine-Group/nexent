// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Fragment, useId, useMemo, useRef, type ReactNode } from "react";
import { Drawer, Input, Select } from "antd";
import { Check, ChevronDown, RefreshCw, Search, Tag } from "lucide-react";
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
  indeterminate = false,
  disabled = false,
}: {
  checked: boolean;
  onToggle?: () => void;
  ariaLabel?: string;
  indeterminate?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-label={ariaLabel}
      aria-checked={indeterminate ? "mixed" : checked}
      disabled={disabled}
      onClick={onToggle}
      className={cn(
        "flex h-4 w-4 shrink-0 cursor-pointer items-center justify-center rounded-[2px] border",
        checked || indeterminate
          ? "border-[#0067D1] bg-[#0067D1] text-white"
          : "border-[#C9C9C9] bg-white"
      )}
    >
      {indeterminate ? (
        <span className="h-0.5 w-2 bg-current" />
      ) : (
        checked && <Check size={11} strokeWidth={3} />
      )}
    </button>
  );
}

/** Search input plus optional tag dropdown (hidden when no tag options provided). */
export function SearchRow({
  placeholder,
  searchInputType = "text",
  tagOptions,
  tagFilter,
  onSearch,
  onTagChange,
  keyword,
  tag,
  disabled = false,
}: {
  placeholder: string;
  searchInputType?: "text" | "search";
  tagOptions?: TagOption[];
  tagFilter?: ReactNode;
  onSearch?: (keyword: string) => void;
  onTagChange?: (value?: string) => void;
  keyword?: string;
  tag?: string;
  disabled?: boolean;
}) {
  const { t } = useTranslation("common");
  return (
    <div data-picker-part="search" className="flex shrink-0 items-center gap-4">
      <Input
        type={searchInputType}
        disabled={disabled}
        value={keyword}
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
      {tagFilter !== undefined
        ? tagFilter
        : tagOptions && (
            <Select
              disabled={disabled}
              value={tag}
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
  refreshLoading = false,
  extra,
  partiallySelected,
  selectAllDisabled,
  refreshDisabled,
}: {
  title: string;
  onSelectAll?: (checked: boolean) => void;
  allSelected?: boolean;
  onRefresh?: () => void;
  refreshLoading?: boolean;
  extra?: ReactNode;
  partiallySelected?: boolean;
  selectAllDisabled?: boolean;
  refreshDisabled?: boolean;
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
            disabled={refreshDisabled || refreshLoading}
            aria-busy={refreshLoading}
            className="flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-[#2673E5]"
          >
            <RefreshCw
              size={14}
              className={refreshLoading ? "animate-spin" : undefined}
            />
            {t("resourcePicker.refresh", "刷新")}
          </button>
        )}
        {onSelectAll && (
          <span className="flex items-center gap-1.5 text-[#191919]">
            <CheckMark
              checked={allSelected ?? false}
              indeterminate={partiallySelected}
              disabled={selectAllDisabled}
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
  semanticTabs = false,
}: {
  semanticTabs?: boolean;
  tabs: ResourcePickerTab[];
  activeKey: string;
  onChange?: (key: string) => void;
}) {
  return (
    <div
      role={semanticTabs ? "tablist" : undefined}
      data-picker-part="tabs"
      className="flex shrink-0 items-center gap-3"
    >
      {tabs.map((tab, index) => (
        <Fragment key={tab.key}>
          {index > 0 && <span className="h-[14px] w-px bg-[#D9D9D9]" />}
          <button
            type="button"
            role={semanticTabs ? "tab" : undefined}
            aria-selected={semanticTabs ? activeKey === tab.key : undefined}
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
  pageSizeOptions = [10, 20, 50],
  current,
  onPageChange,
  onPageSizeChange,
  disabled = false,
}: {
  total: number;
  pageSize?: number;
  pageSizeOptions?: number[];
  current: number;
  onPageChange: (page: number) => void;
  onPageSizeChange?: (pageSize: number) => void;
  disabled?: boolean;
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
      className="flex min-h-8 w-full shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-2"
    >
      <div className="flex shrink-0 items-center gap-4">
        <span className="shrink-0 whitespace-nowrap text-[14px] leading-[22px] text-[#191919]">
          {t("resourcePicker.total", "总计")}: {total}
        </span>
        <Select
          value={pageSize}
          disabled={disabled || !onPageSizeChange}
          onChange={onPageSizeChange}
          options={[...new Set([pageSize, ...pageSizeOptions])]
            .sort((left, right) => left - right)
            .map((size) => ({
              value: size,
              label: `${size} ${t("resourcePicker.perPage", "条/页")}`,
            }))}
          suffixIcon={<ChevronDown size={12} className="text-[#666]" />}
          className="w-[140px]"
          styles={{ root: { width: 140 } }}
          variant="outlined"
        />
      </div>
      <div className="ml-auto flex max-w-full flex-wrap items-center justify-end gap-4">
        <div className="flex shrink-0 items-center gap-1">
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
        <div className="flex h-8 w-[96px] shrink-0 items-center rounded-[4px] border border-[#D9D9D9] bg-white">
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
    </div>
  );
}

export interface ResourceDrawerProps {
  /** Optional presentation overrides; the default resource drawers retain their layout. */
  width?: number | string;
  bodyClassName?: string;
  open: boolean;
  disabled?: boolean;
  title: ReactNode;
  searchPlaceholder?: string;
  searchInputType?: "text" | "search";
  keyword?: string;
  tag?: string;
  selected?: SelectedItem[];
  tagOptions?: TagOption[];
  tagFilter?: ReactNode;
  listTitle?: string;
  tabs?: ResourcePickerTab[];
  semanticTabs?: boolean;
  activeTab?: string;
  showConfirm?: boolean;
  total?: number;
  page?: number;
  pageSize?: number;
  pageSizeOptions?: number[];
  onPageSizeChange?: (pageSize: number) => void;
  onPageChange?: (page: number) => void;
  onClose: () => void;
  onConfirm?: () => void;
  confirmDisabled?: boolean;
  confirmLoading?: boolean;
  footerLeading?: ReactNode;
  confirmText?: string;
  closeText?: string;
  onRemoveSelected?: (id: string) => void;
  onSearch?: (keyword: string) => void;
  onTagChange?: (value?: string) => void;
  onTabChange?: (key: string) => void;
  onSelectAll?: (checked: boolean) => void;
  onRefresh?: () => void;
  refreshLoading?: boolean;
  allSelected?: boolean;
  partiallySelected?: boolean;
  selectAllDisabled?: boolean;
  refreshDisabled?: boolean;
  selectedTrailing?: ReactNode;
  children: ReactNode;
  /** Fixed controls above the scrollable resource content. */
  controlsContent?: ReactNode;
  contentClassName?: string;
  paginationContent?: ReactNode;
  /** Use the same drawer shell with an existing resource controller's filters. */
  searchContent?: ReactNode;
  showSelection?: boolean;
  showListHeader?: boolean;
  /** Extra action rendered to the left of the refresh button in the list header. */
  listHeaderExtra?: ReactNode;
  /** Omit to hide tag management in consumers such as Workbench. */
  tagManagement?: {
    onClick: () => void;
    disabled?: boolean;
  };
  showPagination?: boolean;
}

/**
 * Shared skeleton for the five "add resource" right-side drawers.
 * Header, search row, selected chips, list header, tabs, pagination and footer
 * buttons are identical across the five designs; only the list body differs.
 */
export function ResourceDrawer({
  width = "min(760px, 100vw)",
  bodyClassName,
  open,
  disabled = false,
  title,
  searchPlaceholder,
  searchInputType,
  keyword,
  tag,
  selected,
  tagOptions,
  tagFilter,
  listTitle,
  tabs,
  semanticTabs = false,
  activeTab,
  showConfirm = true,
  total,
  page = 1,
  pageSize = 10,
  pageSizeOptions,
  onPageSizeChange,
  onPageChange,
  onClose,
  onConfirm,
  confirmDisabled = false,
  confirmLoading = false,
  footerLeading,
  confirmText,
  closeText,
  onRemoveSelected,
  onSearch,
  onTagChange,
  onTabChange,
  onSelectAll,
  onRefresh,
  refreshLoading,
  allSelected,
  partiallySelected,
  selectAllDisabled,
  refreshDisabled,
  selectedTrailing,
  children,
  controlsContent,
  contentClassName,
  paginationContent,
  searchContent,
  showSelection = selected !== undefined,
  showListHeader = listTitle !== undefined,
  listHeaderExtra,
  tagManagement,
  showPagination = total !== undefined && onPageChange !== undefined,
}: ResourceDrawerProps) {
  const { t } = useTranslation("common");
  const titleId = useId();
  const handleClose = () => {
    if (!confirmLoading) onClose();
  };

  return (
    <Drawer
      aria-labelledby={titleId}
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
          id={titleId}
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

      <fieldset
        disabled={disabled || confirmLoading}
        className="m-0 flex min-h-0 min-w-0 flex-1 flex-col gap-4 border-0 p-0"
      >
        {searchContent !== undefined ? (
          searchContent
        ) : searchPlaceholder !== undefined ? (
          <SearchRow
            placeholder={searchPlaceholder}
            searchInputType={searchInputType}
            keyword={keyword}
            tag={tag}
            disabled={disabled || confirmLoading}
            tagOptions={tagOptions}
            tagFilter={tagFilter}
            onSearch={onSearch}
            onTagChange={onTagChange}
          />
        ) : null}

        {showSelection && (
          <div data-picker-part="selection" className="contents">
            <div className="shrink-0 text-[14px] leading-[20px] text-[#999999]">
              {t("resourcePicker.selected", "已选")} {selected?.length ?? 0}
            </div>
            <SelectedChips
              items={selected ?? []}
              onRemove={onRemoveSelected}
              trailing={selectedTrailing}
            />
          </div>
        )}

        <div data-picker-part="list-heading" className="contents">
          {showListHeader && (
            <ListHeader
              title={listTitle ?? ""}
              onSelectAll={onSelectAll}
              allSelected={allSelected}
              partiallySelected={partiallySelected}
              selectAllDisabled={selectAllDisabled}
              refreshDisabled={refreshDisabled}
              onRefresh={onRefresh}
              refreshLoading={refreshLoading}
              extra={
                <>
                  {tagManagement && (
                    <button
                      type="button"
                      onClick={tagManagement.onClick}
                      disabled={
                        tagManagement.disabled || disabled || confirmLoading
                      }
                      className="flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-[#2673E5] disabled:cursor-not-allowed disabled:text-[#B3B3B3]"
                    >
                      <Tag size={14} />
                      {t("resourcePicker.manageTags", "管理标签")}
                    </button>
                  )}
                  {listHeaderExtra}
                </>
              }
            />
          )}

          {tabs && activeTab !== undefined && (
            <ResourceTabs
              tabs={tabs}
              semanticTabs={semanticTabs}
              activeKey={activeTab}
              onChange={onTabChange}
            />
          )}
        </div>

        {controlsContent !== undefined && (
          <div data-picker-part="controls" className="shrink-0">
            {controlsContent}
          </div>
        )}

        <div
          data-picker-part="list-content"
          data-resource-list
          className={cn("min-h-0 flex-1 overflow-y-auto", contentClassName)}
        >
          {children}
        </div>

        {(paginationContent != null ||
          (paginationContent === undefined && showPagination)) && (
          <div data-resource-pagination className="shrink-0 [&>div]:mt-0">
            {paginationContent !== undefined ? (
              paginationContent
            ) : (
              <ResourcePagination
                total={total ?? 0}
                current={page}
                pageSize={pageSize}
                pageSizeOptions={pageSizeOptions}
                onPageSizeChange={onPageSizeChange}
                disabled={disabled || confirmLoading}
                onPageChange={onPageChange ?? (() => {})}
              />
            )}
          </div>
        )}
      </fieldset>
      <div
        data-picker-part="footer"
        className="flex shrink-0 justify-end gap-3"
      >
        {footerLeading && <div className="mr-auto">{footerLeading}</div>}
        <button
          type="button"
          onClick={handleClose}
          disabled={confirmLoading}
          className="h-8 w-[89px] cursor-pointer rounded-[2px] border border-[#C9C9C9] bg-white text-[14px] leading-[22px] text-[#191919]"
        >
          {closeText ?? t("resourcePicker.close", "关闭")}
        </button>
        {showConfirm && (
          <button
            type="button"
            onClick={onConfirm}
            disabled={disabled || confirmDisabled || confirmLoading}
            aria-busy={confirmLoading}
            className="inline-flex h-8 w-[89px] cursor-pointer items-center justify-center gap-2 rounded-[2px] border-0 bg-[#1476FF] text-[14px] leading-[22px] text-white"
          >
            {confirmLoading && (
              <RefreshCw aria-hidden size={14} className="animate-spin" />
            )}
            {confirmText ?? t("resourcePicker.confirm", "确认")}
          </button>
        )}
      </div>
    </Drawer>
  );
}
