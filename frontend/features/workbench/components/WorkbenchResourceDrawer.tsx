// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { AddResourceDrawer } from "@/components/resource-picker/AddResourceDrawer";
import {
  ResourceDrawer,
  type ResourceDrawerProps,
} from "@/components/resource-picker/ResourceDrawer";

/** Presentation only: the owning controller manages drafts and persistence. */
export function WorkbenchResourceDrawer({
  open,
  title,
  onCancel,
  onConfirm,
  saving = false,
  disabled = false,
  confirmDisabled = false,
  footerLeading,
  children,
  listContent,
  pagination,
  picker,
}: {
  open: boolean;
  title: ReactNode;
  onCancel: () => void;
  onConfirm: () => void;
  saving?: boolean;
  disabled?: boolean;
  confirmDisabled?: boolean;
  footerLeading?: ReactNode;
  children?: ReactNode;
  listContent?: ReactNode;
  pagination?: ReactNode;
  picker?: Omit<
    ResourceDrawerProps,
    "children" | "open" | "title" | "onClose" | "onConfirm" | "tagManagement"
  >;
}) {
  const { t } = useTranslation();
  if (picker)
    return (
      <>
        <ResourceDrawer
          {...picker}
          semanticTabs
          pageSizeOptions={[10, 20, 50]}
          searchInputType="search"
          open={open}
          title={title}
          width="min(768px, 100vw)"
          disabled={disabled}
          tagManagement={undefined}
          onClose={() => {
            if (!saving) onCancel();
          }}
          onConfirm={onConfirm}
          confirmLoading={saving}
          confirmDisabled={confirmDisabled}
          closeText={undefined}
          confirmText={undefined}
          footerLeading={undefined}
        >
          {listContent}
        </ResourceDrawer>
        {children}
      </>
    );
  return (
    <AddResourceDrawer
      size="min(760px, 100vw)"
      open={open}
      title={title}
      selected={[]}
      total={0}
      listTitle=""
      searchPlaceholder=""
      searchContent={null}
      showSelection={false}
      showListHeader={false}
      showPagination={false}
      paginationContent={
        pagination && (
          <div data-resource-pagination className="shrink-0 [&>div]:mt-0">
            {pagination}
          </div>
        )
      }
      contentClassName={
        listContent !== undefined ? "overflow-hidden" : undefined
      }
      closeText={t("common.cancel", "取消")}
      onClose={() => {
        if (!saving) onCancel();
      }}
      onConfirm={onConfirm}
      confirmLoading={saving}
      confirmDisabled={disabled || confirmDisabled}
      footerLeading={
        footerLeading && (
          <fieldset disabled={disabled || saving} className="contents">
            {footerLeading}
          </fieldset>
        )
      }
      confirmText={t("workbench.controls.confirm", "确认选择")}
    >
      <fieldset
        disabled={disabled || saving}
        className={
          listContent !== undefined
            ? "m-0 flex h-full min-h-0 min-w-0 flex-col border-0 p-0"
            : "min-w-0 border-0 p-0"
        }
      >
        <div className="shrink-0">{children}</div>
        {listContent !== undefined && (
          <div
            data-resource-list
            className="mt-3 min-h-0 flex-1 overflow-y-auto rounded-lg border border-border"
          >
            {listContent}
          </div>
        )}
      </fieldset>
    </AddResourceDrawer>
  );
}
