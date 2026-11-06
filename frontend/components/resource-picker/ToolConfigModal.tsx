// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";

import { useEffect, useState } from "react";

import {
  ParamDialog,
  ParamField,
  ParamInput,
  SectionHeader,
  TestResultArea,
  TestRunLink,
} from "./ParamDialog";

const CONFIG_FIELDS = [
  { key: "host", label: "host", required: true },
  { key: "port", label: "port", required: true },
  { key: "username", label: "username", required: true },
  { key: "password", label: "password", required: true },
  { key: "database", label: "database", required: true },
  { key: "encrypt", label: "encrypt", required: false },
];

const TEST_FIELDS = [
  { key: "host", label: "host" },
  { key: "port", label: "port" },
  { key: "username", label: "username" },
  { key: "password", label: "password" },
  { key: "database", label: "database" },
];

export interface ToolConfigModalProps {
  open: boolean;
  onClose: () => void;
  onConfirm?: (values: Record<string, string>) => void;
  /** Configuration and debugging modes share the same parameter values. */
  mode?: "config" | "debug";
  toolName?: string;
}

export function ToolConfigModal({
  open,
  onClose,
  onConfirm,
  mode = "config",
  toolName = "mssql_database",
}: ToolConfigModalProps) {
  const { t } = useTranslation();
  const [paramsExpanded, setParamsExpanded] = useState(mode === "config");
  const [testExpanded, setTestExpanded] = useState(mode === "debug");
  const [values, setValues] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!open) return;
    setParamsExpanded(mode === "config");
    setTestExpanded(mode === "debug");
  }, [mode, open]);

  const setValue = (key: string, value: string) =>
    setValues((prev) => ({ ...prev, [key]: value }));

  const testBlock = (
    <>
      {TEST_FIELDS.map((field) => (
        <ParamField key={field.key} label={field.label} info size="md">
          <ParamInput
            placeholder={t("ui.localization.sqlServerPlaceholder")}
            value={values[field.key] ?? ""}
            onChange={(e) => setValue(field.key, e.target.value)}
          />
        </ParamField>
      ))}
      <TestRunLink />
      <TestResultArea />
    </>
  );

  return (
    <ParamDialog
      variant="tool"
      description={t("ui.localization.sqlServerDescription")}
      open={open}
      title={t("ui.localization.resourceConfiguration", { name: toolName })}
      onClose={onClose}
      onConfirm={() => onConfirm?.(values)}
    >
      <p className="text-[12px] leading-[18px] text-[#191919]/40">
        {t("ui.localization.sqlServerDescription")}
      </p>

      {mode === "config" ? (
        <>
          <SectionHeader
            title={t("ui.localization.parameterConfiguration")}
            expanded={paramsExpanded}
            onToggle={() => setParamsExpanded((v) => !v)}
          />
          {paramsExpanded &&
            CONFIG_FIELDS.map((field) => (
              <ParamField
                key={field.key}
                label={field.label}
                required={field.required}
                info
                size="md"
              >
                <ParamInput
                  placeholder={t("ui.localization.sqlServerPlaceholder")}
                  value={values[field.key] ?? ""}
                  onChange={(e) => setValue(field.key, e.target.value)}
                />
              </ParamField>
            ))}
          <SectionHeader
            title={t("ui.localization.toolTest")}
            expanded={testExpanded}
            onToggle={() => setTestExpanded((v) => !v)}
          />
          {testExpanded && testBlock}
        </>
      ) : (
        <>
          <ParamInput placeholder={t("ui.localization.sqlServerPlaceholder")} />
          <SectionHeader
            title={t("ui.localization.toolTest")}
            expanded={testExpanded}
            onToggle={() => setTestExpanded((v) => !v)}
          />
          {testExpanded && testBlock}
        </>
      )}
    </ParamDialog>
  );
}
