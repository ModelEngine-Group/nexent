// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { App } from "antd";
import type { UseQueryResult } from "@tanstack/react-query";

import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { getAidpPlainMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import type { AidpKbDetail } from "@/ext_components/aidp/shared/types/management";
import log from "@/lib/logger";

/** Open/save the knowledge-base security guardrail switch. */
export const useAidpGuardrailSettings = (
  knowledgeBaseId: string,
  detailQuery: UseQueryResult<AidpKbDetail, Error>
) => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [saving, setSaving] = useState(false);

  const openModal = async () => {
    setEnabled(detailQuery.data?.sensitive_intercept_enable === 1);
    setOpen(true);
    try {
      // Read the latest KB detail so a stale cache cannot flip the switch the
      // wrong way. The shared query key also refreshes the parent detail view.
      const result = await detailQuery.refetch();
      if (result.data) {
        setEnabled(result.data.sensitive_intercept_enable === 1);
      }
    } catch {
      // Keep the cached value; save errors are reported separately.
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      await aidpKnowledgeService.updateKb(knowledgeBaseId, {
        sensitive_intercept_enable: enabled ? 1 : 0,
      });
      message.success(t("aidpSensitiveWords.guardrailSaveSuccess"));
      setOpen(false);
      await detailQuery.refetch();
    } catch (error) {
      log.error("Failed to update AIDP sensitive word guardrails:", {
        id: knowledgeBaseId,
        error,
      });
      message.error(
        getAidpPlainMessage(error, t("aidpSensitiveWords.guardrailSaveFailed"))
      );
    } finally {
      setSaving(false);
    }
  };

  return {
    open,
    setOpen,
    enabled,
    setEnabled,
    saving,
    openModal,
    save,
  };
};
