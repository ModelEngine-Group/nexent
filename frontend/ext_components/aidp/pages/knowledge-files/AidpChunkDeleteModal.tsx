// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Button, Modal } from "antd";

import styles from "./AidpSemanticChunks.module.css";

interface AidpChunkDeleteModalProps {
  open: boolean;
  /** Number of chunks in the pending removal request. */
  count: number;
  submitting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

/**
 * Removal confirmation.
 *
 * The dialog only states what the UI itself does (the chunks disappear from
 * this file's list). AIDP has not documented when the vector, full-text and
 * graph indexes catch up, so the copy does not promise an immediate or
 * complete effect on retrieval.
 */
const AidpChunkDeleteModal: React.FC<AidpChunkDeleteModalProps> = ({
  open,
  count,
  submitting,
  onCancel,
  onConfirm,
}) => {
  const { t } = useTranslation();

  return (
    <Modal
      open={open}
      onCancel={onCancel}
      footer={null}
      width={608}
      centered
      closable={false}
      mask={{ closable: !submitting }}
      keyboard={!submitting}
      styles={{ container: { padding: 0, borderRadius: 8 } }}
    >
      <div className={styles.deleteDialog}>
        <h2 className={styles.deleteTitle}>
          {t("aidpKnowledge.chunkDeleteTitle")}
        </h2>
        <p className={styles.deleteBody}>
          {t("aidpKnowledge.chunkDeleteBody", { count })}
        </p>
        <p className={styles.deleteImpact}>
          {t("aidpKnowledge.chunkDeleteImpact")}
        </p>
        <div className={styles.deleteActions}>
          <Button
            onClick={onCancel}
            disabled={submitting}
            style={{ minWidth: 88, height: 32 }}
          >
            {t("common.cancel")}
          </Button>
          <Button
            danger
            loading={submitting}
            onClick={onConfirm}
            style={{ minWidth: 88, height: 32 }}
          >
            {t("aidpKnowledge.chunkDelete")}
          </Button>
        </div>
      </div>
    </Modal>
  );
};

export default AidpChunkDeleteModal;
