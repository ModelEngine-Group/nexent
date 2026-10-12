"use client";

import { useEffect, useState } from "react";

import {
  ParamDialog,
  ParamField,
  ParamInput,
  SectionHeader,
  TestResultArea,
  TestRunLink,
} from "./ParamDialog";

const DESCRIPTION =
  "在 Microsoft SQL Server 数据库上执行 SQL 查询。该工具为 AI 智能体提供标准化的 SQL Server 数据库操作接口，支持参数绑定和安全控制，安全限制：禁止...";

const PLACEHOLDER = "请输入SQL Sever database or domain";

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
  /** "config" = 参数配置态, "debug" = 调试态. */
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
            placeholder={PLACEHOLDER}
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
      open={open}
      title={`${toolName} 配置`}
      onClose={onClose}
      onConfirm={() => onConfirm?.(values)}
    >
      <p className="text-[12px] leading-[18px] text-[#191919]/40">{DESCRIPTION}</p>

      {mode === "config" ? (
        <>
          <SectionHeader
            title="参数配置"
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
                  placeholder={PLACEHOLDER}
                  value={values[field.key] ?? ""}
                  onChange={(e) => setValue(field.key, e.target.value)}
                />
              </ParamField>
            ))}
          <SectionHeader
            title="工具测试"
            expanded={testExpanded}
            onToggle={() => setTestExpanded((v) => !v)}
          />
          {testExpanded && testBlock}
        </>
      ) : (
        <>
          <ParamInput placeholder={PLACEHOLDER} />
          <SectionHeader
            title="工具测试"
            expanded={testExpanded}
            onToggle={() => setTestExpanded((v) => !v)}
          />
          {testExpanded && testBlock}
        </>
      )}
    </ParamDialog>
  );
}