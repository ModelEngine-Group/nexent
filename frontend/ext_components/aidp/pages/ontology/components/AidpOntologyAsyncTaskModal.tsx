// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Button, Descriptions, Modal, Progress } from "antd";

import styles from "./AidpOntologyAsyncTaskModal.module.css";

export type AidpOntologyTaskState = "running" | "success" | "failed";

interface AidpOntologyAsyncTaskModalProps {
  open: boolean;
  /** Human-readable task name, e.g. 解绑关联 Chunk. */
  taskName: string;
  taskId?: string | null;
  /** True only when this deployment is wired to the local demo data source. */
  demo: boolean;
  initialState?: AidpOntologyTaskState;
  onClose: () => void;
}

const PROGRESS: Record<AidpOntologyTaskState, number> = {
  running: 30,
  success: 100,
  failed: 20,
};

const AidpOntologyAsyncTaskModal: React.FC<AidpOntologyAsyncTaskModalProps> = ({
  open,
  taskName,
  taskId,
  demo,
  initialState = "running",
  onClose,
}) => {
  const { t } = useTranslation();
  const shownState = initialState;
  const modalTitle = demo
    ? shownState === "running"
      ? `${taskName}执行中`
      : shownState === "success"
        ? `${taskName}成功`
        : `${taskName}失败，请重试`
    : `${taskName}已受理`;

  return (
    <Modal
      open={open}
      width={560}
      title={modalTitle}
      onCancel={onClose}
      centered
      footer={
        <div className={styles.footer}>
          <Button type="primary" onClick={onClose}>
            {t("common.close")}
          </Button>
        </div>
      }
    >
      <div className={styles.body}>
        <Descriptions
          size="small"
          column={1}
          bordered
          items={[
            {
              key: "taskId",
              label: t("aidpKnowledge.ontologyAsyncTaskId"),
              children: taskId || t("aidpKnowledge.ontologyDash"),
            },
          ]}
        />

        {!demo && taskId ? (
          <div className={styles.accepted}>
            <div className={styles.acceptedTitle}>
              {t("aidpKnowledge.ontologyAsyncTaskAcceptedTitle")}
            </div>
            <div className={styles.acceptedText}>
              {t("aidpKnowledge.ontologyAsyncTaskAcceptedText")}
            </div>
          </div>
        ) : (
          <>
            <div className={styles.progressLabel}>
              {t("aidpKnowledge.ontologyAsyncTaskProgress")}
            </div>
            <Progress
              percent={PROGRESS[shownState]}
              status={
                shownState === "failed"
                  ? "exception"
                  : shownState === "success"
                    ? "success"
                    : "active"
              }
            />
            <div className={styles.stateLine}>
              {shownState === "running" &&
                t("aidpKnowledge.ontologyAsyncTaskRunningHint")}
              {shownState === "success" &&
                t("aidpKnowledge.ontologyAsyncTaskSuccessHint")}
              {shownState === "failed" && (
                <span className={styles.failText}>
                  {t("aidpKnowledge.ontologyAsyncTaskFailedHint")}
                </span>
              )}
            </div>
          </>
        )}
      </div>
    </Modal>
  );
};

export default AidpOntologyAsyncTaskModal;
