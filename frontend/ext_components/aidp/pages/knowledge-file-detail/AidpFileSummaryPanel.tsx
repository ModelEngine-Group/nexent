// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, Spin, Tooltip } from "antd";
import { ReloadOutlined } from "@ant-design/icons";

import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import type { AidpFileSummary } from "@/ext_components/aidp/shared/types/summary";
import { useAidpFileSummary } from "./hooks/useAidpFileSummary";
import styles from "./AidpFileSummary.module.css";

interface AidpFileSummaryPanelProps {
  kdsId: string;
  fileUuid: string;
  /** KB summary_preview; when false AIDP returns an empty result. */
  previewEnabled: boolean;
}

/**
 * File summary tab.
 *
 * States come from AIDP's `result`: pending is polled by the query, success
 * renders `summary_text`, failed shows `error_reason`. An empty result is
 * interpreted together with the KB's `summary_preview` flag and is never
 * reported as a generation failure. AIDP has no summary-retry endpoint, so the
 * failed state is read-only.
 */
const AidpFileSummaryPanel: React.FC<AidpFileSummaryPanelProps> = ({
  kdsId,
  fileUuid,
  previewEnabled,
}) => {
  const { t } = useTranslation();
  const query = useAidpFileSummary(kdsId, fileUuid, true, previewEnabled);
  const summary: AidpFileSummary = useMemo(
    () => query.data?.result ?? {},
    [query.data]
  );
  const status = summary.summary_status ?? "";
  const text = summary.summary_text ?? "";
  const model = summary.summary_model ?? "";
  const reason = summary.error_reason;
  const isPending = status === "pending";
  const isFailed = status === "failed";
  const isSuccess = status === "success";

  if (query.isError) {
    return (
      <div className={styles.panel}>
        <Alert
          type="error"
          showIcon
          title={getAidpErrorMessage(
            query.error,
            t,
            t("aidpKnowledge.fileSummaryLoadFailed")
          )}
          action={
            <Button size="small" onClick={() => void query.refetch()}>
              {t("aidpKnowledge.chunksRetry")}
            </Button>
          }
        />
      </div>
    );
  }

  if (query.isPending) {
    return (
      <div className={styles.panel}>
        <div className={styles.state}>
          <Spin />
          <span>{t("aidpKnowledge.fileSummaryLoading")}</span>
        </div>
      </div>
    );
  }

  if (!previewEnabled) {
    return (
      <div className={styles.panel}>
        <Alert
          type="info"
          showIcon
          title={t("aidpKnowledge.fileSummaryUnavailable")}
          description={t("aidpKnowledge.fileSummaryUnavailableHint")}
        />
      </div>
    );
  }

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <h3 className={styles.title}>{t("aidpKnowledge.fileSummaryTitle")}</h3>
        <div className="flex items-center gap-2">
          {model && isSuccess && (
            <span className={styles.meta}>
              {t("aidpKnowledge.fileSummaryModel")}: {model}
            </span>
          )}
          <Tooltip title={t("aidpKnowledge.fileSummaryRefresh")}>
            <Button
              type="text"
              size="small"
              aria-label={t("aidpKnowledge.fileSummaryRefresh")}
              icon={<ReloadOutlined spin={query.isFetching} />}
              onClick={() => void query.refetch()}
            />
          </Tooltip>
        </div>
      </div>

      {isFailed ? (
        <div className={styles.state}>
          <Alert
            type="error"
            showIcon
            title={t("aidpKnowledge.fileSummaryFailed")}
            description={reason}
          />
        </div>
      ) : isPending ? (
        <div className={styles.state}>
          <Spin />
          <span>{t("aidpKnowledge.fileSummaryGenerating")}</span>
        </div>
      ) : isSuccess ? (
        <div className={styles.text}>
          {text || t("aidpKnowledge.fileSummaryEmpty")}
        </div>
      ) : (
        <div className={styles.state}>
          <span>{t("aidpKnowledge.fileSummaryEmpty")}</span>
        </div>
      )}
    </div>
  );
};

export default AidpFileSummaryPanel;
