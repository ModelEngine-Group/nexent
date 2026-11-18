// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, App, Button, Spin, Tooltip } from "antd";
import { ReloadOutlined } from "@ant-design/icons";

import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import type {
  AidpFileSummary,
  AidpSummaryRetryItem,
  AidpSummaryRetryResponse,
} from "@/ext_components/aidp/shared/types/summary";
import log from "@/lib/logger";
import { useAidpFileSummary } from "./hooks/useAidpFileSummary";
import styles from "./AidpFileSummary.module.css";

interface AidpFileSummaryPanelProps {
  kdsId: string;
  fileUuid: string;
  canEdit: boolean;
  /** KB summary_preview; when false AIDP returns an empty result. */
  previewEnabled: boolean;
}

const readReason = (summary: AidpFileSummary): string | undefined => {
  for (const key of ["message", "reason", "error_message"]) {
    const value = summary[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return undefined;
};

const retryItemReason = (
  item: AidpSummaryRetryItem | string | undefined
): string | undefined => {
  if (!item || typeof item === "string") return undefined;
  const message = item.message || item.reason;
  if (typeof message === "string" && message.trim()) return message.trim();
  return item.err_code === undefined || item.err_code === null
    ? undefined
    : String(item.err_code);
};

const findRetryItem = (
  items: AidpSummaryRetryResponse["partial_success_list"] | undefined,
  fileUuid: string
) =>
  (items ?? []).find((item) =>
    typeof item === "string" ? item === fileUuid : item.file_uuid === fileUuid
  );

/**
 * File summary tab.
 *
 * States come from AIDP's `result`: pending is polled by the query, success
 * renders `summary_text`, failed offers a per-file retry when the user has EDIT
 * permission. An empty result is interpreted together with the KB's
 * `summary_preview` flag and is never reported as a generation failure.
 */
const AidpFileSummaryPanel: React.FC<AidpFileSummaryPanelProps> = ({
  kdsId,
  fileUuid,
  canEdit,
  previewEnabled,
}) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [retrying, setRetrying] = useState(false);
  const query = useAidpFileSummary(kdsId, fileUuid, true, previewEnabled);
  const summary: AidpFileSummary = useMemo(
    () => query.data?.result ?? {},
    [query.data]
  );
  const status = summary.summary_status?.toString().toLowerCase() ?? "";
  const text =
    typeof summary.summary_text === "string" ? summary.summary_text : "";
  const model =
    typeof summary.summary_model === "string" ? summary.summary_model : "";
  const reason = readReason(summary);
  const isPending = status === "pending" || (!status && !text);
  const isFailed = status === "failed";
  const isSuccess = status === "success" || (!status && !!text);

  const retry = useCallback(async () => {
    setRetrying(true);
    try {
      const result = await aidpKnowledgeService.retryFileSummaries(kdsId, [
        fileUuid,
      ]);
      const failed = findRetryItem(result.failed_list, fileUuid);
      const succeeded = findRetryItem(result.partial_success_list, fileUuid);
      if (failed) {
        message.error(
          t("aidpKnowledge.fileSummaryRetryFailed", {
            reason: retryItemReason(failed) || t("aidpKnowledge.chunkUnknown"),
          })
        );
      } else if (succeeded) {
        message.success(t("aidpKnowledge.fileSummaryRetrySuccess"));
      } else {
        message.warning(t("aidpKnowledge.fileSummaryRetrySubmitted"));
      }
      await query.refetch();
    } catch (error) {
      log.error("Failed to retry AIDP file summary:", {
        kdsId,
        fileUuid,
        error,
      });
      message.error(
        getAidpErrorMessage(
          error,
          t,
          t("aidpKnowledge.fileSummaryRetryFailedShort")
        )
      );
    } finally {
      setRetrying(false);
    }
  }, [fileUuid, kdsId, message, query, t]);

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
          {canEdit && (
            <div className={styles.retryActions}>
              <Button
                type="primary"
                loading={retrying}
                onClick={() => void retry()}
              >
                {t("aidpKnowledge.fileSummaryRetry")}
              </Button>
            </div>
          )}
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
