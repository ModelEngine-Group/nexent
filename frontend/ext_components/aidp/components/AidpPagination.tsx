"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import { Pagination } from "antd";

interface AidpPaginationProps {
  currentPage: number;
  pageSize: number;
  total: number;
  /** True when `total` came from the AIDP Count API. */
  totalReliable: boolean;
  hasMore: boolean;
  onPageChange: (page: number) => void;
  onPageSizeChange?: (pageSize: number) => void;
}

/**
 * Server-side pagination shared by the AIDP knowledge base and document lists.
 *
 * AIDP exposes a dedicated Count API; when it succeeds `totalReliable` is true
 * and the full control including the total is shown. When Count fails the total
 * is only a fallback estimate, so the control degrades to simple prev/next mode
 * driven by `hasMore` and omits the total.
 */
const AidpPagination: React.FC<AidpPaginationProps> = ({
  currentPage,
  pageSize,
  total,
  totalReliable,
  hasMore,
  onPageChange,
  onPageSizeChange,
}) => {
  const { t } = useTranslation();
  // When the total is unreliable the control still needs a value that enables
  // "next": set it just past the current page when another page exists,
  // otherwise clamp it to the current page end.
  const effectiveTotal = totalReliable
    ? total
    : hasMore
      ? currentPage * pageSize + 1
      : currentPage * pageSize;

  return (
    <Pagination
      current={currentPage}
      pageSize={pageSize}
      total={effectiveTotal || 1}
      onChange={(page, nextPageSize) => {
        if (onPageSizeChange && nextPageSize !== pageSize) {
          onPageSizeChange(nextPageSize);
          return;
        }
        onPageChange(page);
      }}
      pageSizeOptions={onPageSizeChange ? [10, 20, 50, 100] : undefined}
      showSizeChanger={Boolean(onPageSizeChange)}
      simple={!totalReliable}
      showTotal={
        totalReliable
          ? (value) => t("aidpKnowledge.showTotal", { count: value })
          : undefined
      }
      size="small"
    />
  );
};

export default AidpPagination;
