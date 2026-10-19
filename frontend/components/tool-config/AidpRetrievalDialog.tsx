// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useState } from "react";
import { Modal } from "antd";
import { useTranslation } from "react-i18next";
import { AidpRetrievalParamsForm } from "./AidpRetrievalParamsForm";
import { aidpErrors, mergeAidpConfig } from "@/lib/aidpRetrievalConfig";

export function AidpRetrievalDialog({
  values,
  disabled,
  onCancel,
  onConfirm,
}: {
  values: Record<string, unknown>;
  disabled?: boolean;
  onCancel: () => void;
  onConfirm: (config: Record<string, unknown>) => void;
}) {
  const { t } = useTranslation("common");
  const [draft, setDraft] = useState(() => mergeAidpConfig(values));
  return (
    <Modal
      open
      width={480}
      title={t("agent.knowledge.configModal.title")}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      onCancel={onCancel}
      onOk={() => {
        if (!disabled && !Object.keys(aidpErrors(draft)).length)
          onConfirm(draft);
      }}
      okButtonProps={{
        disabled: disabled || Object.keys(aidpErrors(draft)).length > 0,
      }}
    >
      <AidpRetrievalParamsForm
        values={draft}
        disabled={disabled}
        onChange={(patch) => setDraft((current) => ({ ...current, ...patch }))}
      />
    </Modal>
  );
}
