// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import { Modal, Switch } from "antd";

import styles from "./AidpGuardrailSettingsModal.module.css";

interface AidpGuardrailSettingsModalProps {
  open: boolean;
  enabled: boolean;
  loading: boolean;
  saving: boolean;
  onToggle: (enabled: boolean) => void;
  onSave: () => void;
  onCancel: () => void;
}

/** One-switch editor for the knowledge-base guardrail setting. */
const AidpGuardrailSettingsModal: React.FC<AidpGuardrailSettingsModalProps> = ({
  open,
  enabled,
  loading,
  saving,
  onToggle,
  onSave,
  onCancel,
}) => {
  const { t } = useTranslation();

  return (
    <Modal
      open={open}
      title={t("aidpSensitiveWords.guardrailEdit")}
      onOk={() => void onSave()}
      onCancel={onCancel}
      okText={t("common.save")}
      cancelText={t("common.cancel")}
      confirmLoading={saving}
      okButtonProps={{ disabled: loading }}
      centered
      width={520}
      closable={!saving}
      maskClosable={!saving}
      keyboard={!saving}
    >
      <div className={styles.guardrailModal}>
        <div className={styles.guardrailModalControl}>
          <span className={styles.guardrailModalLabel}>
            {t("aidpKnowledge.sensitiveIntercept")}
          </span>
          <Switch
            checked={enabled}
            loading={loading}
            onChange={onToggle}
            aria-label={t("aidpKnowledge.sensitiveIntercept")}
          />
        </div>
        <p className={styles.guardrailModalHint}>
          {t("aidpSensitiveWords.guardrailSwitchHint")}
        </p>
      </div>
    </Modal>
  );
};

export default AidpGuardrailSettingsModal;
