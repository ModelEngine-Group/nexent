// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, App, Button, Modal, Select } from "antd";

import styles from "./AidpSemanticChunks.module.css";

interface AidpBatchTagModalProps {
  open: boolean;
  tagOptions: string[];
  count: number;
  mode: "file" | "chunk";
  submitting: boolean;
  onClose: () => void;
  onSubmit: (tags: string[]) => Promise<void>;
}

/**
 * Replace the complete tag set of every chunk in the chosen scope.
 *
 * AIDP treats the tag list as a replacement, so an empty list clears every
 * tag. The empty submit is guarded by a second confirmation.
 */
const AidpBatchTagModal: React.FC<AidpBatchTagModalProps> = ({
  open,
  tagOptions,
  count,
  mode,
  submitting,
  onClose,
  onSubmit,
}) => {
  const { t } = useTranslation();
  const { modal } = App.useApp();
  const [selected, setSelected] = useState<string[]>([]);

  const options = useMemo(
    () => tagOptions.map((tag) => ({ value: tag, label: tag })),
    [tagOptions]
  );

  const submit = async (tags: string[]) => {
    try {
      await onSubmit(tags);
    } catch {
      // The parent reports the failure; keep the selection for retry.
    }
  };

  const handleSubmit = () => {
    if (selected.length > 0) {
      void submit(selected);
      return;
    }
    modal.confirm({
      title: t("aidpKnowledge.batchTagsClearTitle"),
      content: t("aidpKnowledge.batchTagsClearBody"),
      okText: t("aidpKnowledge.batchTagsClearConfirm"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      centered: true,
      onOk: () => submit([]),
    });
  };

  return (
    <Modal
      open={open}
      centered
      width={608}
      destroyOnHidden
      closable={false}
      mask={{ closable: !submitting }}
      keyboard={!submitting}
      onCancel={() => {
        if (!submitting) onClose();
      }}
      footer={null}
      styles={{ container: { padding: 0, borderRadius: 8 } }}
    >
      <div className={styles.deleteDialog}>
        <h2 className={styles.deleteTitle}>
          {t("aidpKnowledge.batchTagsTitle")}
        </h2>
        <p className={styles.deleteBody}>
          {mode === "file"
            ? t("aidpKnowledge.batchTagsFileHint", { count })
            : t("aidpKnowledge.batchTagsChunkHint", { count })}
        </p>
        {tagOptions.length === 0 ? (
          <Alert
            type="info"
            showIcon
            title={t("aidpKnowledge.batchTagsEmpty")}
          />
        ) : (
          <Select
            mode="multiple"
            allowClear
            showSearch
            className={styles.batchTagSelect}
            value={selected}
            options={options}
            maxTagCount="responsive"
            placeholder={t("aidpKnowledge.batchTagsPlaceholder")}
            onChange={(values: string[]) => setSelected(values)}
          />
        )}
        <p className={styles.deleteImpact}>
          {t("aidpKnowledge.batchTagsOverwriteHint")}
        </p>
        <div className={styles.deleteActions}>
          <Button onClick={onClose} disabled={submitting}>
            {t("common.cancel")}
          </Button>
          <Button type="primary" loading={submitting} onClick={handleSubmit}>
            {t("common.confirm")}
          </Button>
        </div>
      </div>
    </Modal>
  );
};

export default AidpBatchTagModal;
