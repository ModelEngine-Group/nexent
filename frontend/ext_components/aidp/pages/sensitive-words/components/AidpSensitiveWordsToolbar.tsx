// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import { Button, Input, Tooltip } from "antd";
import {
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
} from "@ant-design/icons";

import styles from "../AidpSensitiveWords.module.css";

interface AidpSensitiveWordsToolbarProps {
  keywordInput: string;
  loading: boolean;
  canManage: boolean;
  selectedCount: number;
  onKeywordChange: (value: string) => void;
  onSearch: () => void;
  onRefresh: () => void;
  onBatchDelete: () => void;
  onCreate: () => void;
}

/** Search and row-level actions for one knowledge base's dictionary. */
const AidpSensitiveWordsToolbar: React.FC<AidpSensitiveWordsToolbarProps> = ({
  keywordInput,
  loading,
  canManage,
  selectedCount,
  onKeywordChange,
  onSearch,
  onRefresh,
  onBatchDelete,
  onCreate,
}) => {
  const { t } = useTranslation();

  return (
    <div className={styles.toolbar}>
      <Input
        allowClear
        className={styles.searchInput}
        placeholder={t("aidpSensitiveWords.searchPlaceholder")}
        prefix={<SearchOutlined />}
        value={keywordInput}
        onChange={(event) => onKeywordChange(event.target.value)}
        onPressEnter={onSearch}
      />
      <div className={styles.toolbarActions}>
        <Tooltip title={t("aidpKnowledge.refresh")}>
          <Button
            aria-label={t("aidpKnowledge.refresh")}
            icon={<ReloadOutlined spin={loading} />}
            onClick={onRefresh}
          />
        </Tooltip>
        {canManage && (
          <>
            <Button disabled={selectedCount === 0} onClick={onBatchDelete}>
              {t("common.delete")}
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={onCreate}>
              {t("aidpSensitiveWords.add")}
            </Button>
          </>
        )}
      </div>
    </div>
  );
};

export default AidpSensitiveWordsToolbar;
