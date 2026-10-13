"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, ConfigProvider, Input, Pagination, Select } from "antd";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import { aidpKnowledgeVisualTheme } from "@/ext_components/aidp/shared/styles/aidpKnowledgeVisualTheme";
import styles from "./AidpPagination.module.css";

interface AidpPaginationProps {
  currentPage: number;
  pageSize: number;
  total: number;
  /** True when the backend reports a confirmed global total. */
  totalReliable: boolean;
  hasMore: boolean;
  onPageChange: (page: number) => void;
  onPageSizeChange?: (pageSize: number) => void;
}

/** Show totals only when known; search pagination uses hasMore. */
const AidpPagination: React.FC<AidpPaginationProps> = ({
  currentPage,
  pageSize,
  total,
  totalReliable,
  hasMore,
  onPageChange,
  onPageSizeChange,
}) => {
  const { t, i18n } = useTranslation();
  const [jumpPage, setJumpPage] = useState("");
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  // When the total is unreliable the control still needs a value that enables
  // "next": set it just past the current page when another page exists,
  // otherwise clamp it to the current page end.
  const effectiveTotal = totalReliable
    ? total
    : hasMore
      ? currentPage * pageSize + 1
      : currentPage * pageSize;

  return (
    <ConfigProvider
      theme={aidpKnowledgeVisualTheme}
      locale={i18n.language.startsWith("zh") ? zhCN : enUS}
    >
      <div className={styles.pagination}>
        {totalReliable && (
          <span className={styles.paginationTotal}>
            {t("aidpKnowledge.showTotal", { count: total })}
          </span>
        )}
        <div className={styles.paginationControls}>
          {onPageSizeChange && (
            <Select
              className={styles.pageSize}
              aria-label={t("aidpKnowledge.pageSize")}
              value={pageSize}
              onChange={onPageSizeChange}
              options={Array.from(new Set([10, 20, 50, 100, pageSize]))
                .sort((a, b) => a - b)
                .map((size) => ({
                  value: size,
                  label: t("aidpKnowledge.pageSizeOption", { size }),
                }))}
            />
          )}
          <Pagination
            className={styles.pageNumbers}
            current={currentPage}
            pageSize={pageSize}
            total={effectiveTotal || 1}
            onChange={onPageChange}
            showSizeChanger={false}
            simple={!totalReliable}
          />
          {totalReliable && pageCount > 1 && (
            <form
              className={styles.pageJump}
              onSubmit={(event) => {
                event.preventDefault();
                const page = Number(jumpPage);
                if (
                  !/^\d+$/.test(jumpPage) ||
                  !Number.isSafeInteger(page) ||
                  page < 1 ||
                  page > pageCount
                )
                  return;
                onPageChange(page);
                setJumpPage("");
              }}
            >
              <Input
                className={styles.pageJumpInput}
                aria-label={t("aidpKnowledge.pageNumber")}
                inputMode="numeric"
                value={jumpPage}
                onChange={(event) =>
                  setJumpPage(event.target.value.replace(/\D/g, ""))
                }
              />
              <Button htmlType="submit" autoInsertSpace={false}>
                {t("aidpKnowledge.jumpPage")}
              </Button>
            </form>
          )}
        </div>
      </div>
    </ConfigProvider>
  );
};

export default AidpPagination;
