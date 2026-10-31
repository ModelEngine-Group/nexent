// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ParamDialog } from "@/components/resource-picker/ParamDialog";
import { AidpRetrievalParamsForm } from "./AidpRetrievalParamsForm";
import {
  aidpDefaults,
  aidpErrors,
  mergeAidpConfig,
} from "@/lib/aidpRetrievalConfig";

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
  const invalid = Object.keys(aidpErrors(draft)).length > 0;
  return (
    <ParamDialog
      open
      variant="tool"
      title={t("aidpRetrieval.title")}
      onClose={onCancel}
      onConfirm={() => {
        if (!disabled && !invalid) onConfirm(draft);
      }}
      confirmDisabled={disabled || invalid}
      onReset={() => setDraft({ ...aidpDefaults })}
      resetText={t("aidpRetrieval.reset")}
      resetDisabled={disabled}
      destroyOnHidden
    >
      <AidpRetrievalParamsForm
        values={draft}
        disabled={disabled}
        scope="agent"
        onChange={(patch) => setDraft((current) => ({ ...current, ...patch }))}
      />
    </ParamDialog>
  );
}
