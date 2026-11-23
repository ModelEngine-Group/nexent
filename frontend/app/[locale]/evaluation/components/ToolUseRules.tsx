// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { Button, Checkbox, Form, Input, InputNumber, Space } from "antd";
import { useTranslation } from "react-i18next";
import type { ToolExpectation } from "@/services/evolutionService";

export interface ToolRuleFields {
  toolRules?: { name: string; min: number; max?: number; args?: string; checkScript?: boolean; stdout?: string; fileCheck?: boolean; files?: string }[];
  toolOrder?: string;
}

export function toolExpectation({ toolRules, toolOrder }: ToolRuleFields): ToolExpectation | undefined {
  if (!toolRules?.length) return undefined;
  return {
    rules: toolRules.map(r => ({
      ...(r.name.trim() === "run_skill_script" && r.fileCheck ? {expected_script_files: JSON.parse(r.files?.trim() || "{}")} : {}),
      ...(r.name.trim() === "run_skill_script" && r.checkScript ? { expected_script_stdout: r.stdout ?? "" } : {}),
      name: r.name.trim(), min_calls: r.min, max_calls: r.max ?? null, arguments: JSON.parse(r.args?.trim() || "{}"),
    })),
    order: toolOrder?.trim() ? toolOrder.split(",").map(n => n.trim()) : undefined,
  };
}

export default function ToolUseRules() {
  const { t } = useTranslation("common");
  const form = Form.useFormInstance();
  const rules = Form.useWatch("toolRules", form);
  return <><Form.List name="toolRules">{(fields, { add, remove }) => <>
    {fields.map(f => <div key={f.key}>
      <Form.Item name={[f.name, "name"]} label={t("evolution.toolName")} rules={[{ required: true, whitespace: true }]}>
        <Input maxLength={180} />
      </Form.Item>
      <Space align="start">
        <Form.Item name={[f.name, "min"]} label={t("evolution.minimumCalls")} rules={[{ required: true }]}>
          <InputNumber min={0} max={512} precision={0} />
        </Form.Item>
        <Form.Item name={[f.name, "max"]} label={t("evolution.maximumCalls")}>
          <InputNumber min={0} max={512} precision={0} />
        </Form.Item>
      </Space>
      <Form.Item name={[f.name, "args"]} label={t("evolution.expectedArguments")} rules={[{
        validator: async (_, value) => {
          if (!value?.trim()) return;
          try {
            const obj = JSON.parse(value);
            if (obj && typeof obj === "object" && !Array.isArray(obj)) return;
          } catch { /* Show the translated field error below. */ }
          throw new Error(t("evolution.invalidArguments"));
        },
      }]}>
        <Input.TextArea rows={2} placeholder={'{"skill_name":"meeting-action-list"}'} />
      </Form.Item>
      {rules?.[f.name]?.name?.trim() === "run_skill_script" && <>
        <Form.Item name={[f.name, "checkScript"]} valuePropName="checked">
          <Checkbox>{t("evolution.checkScript")}</Checkbox>
        </Form.Item>
        {rules[f.name].checkScript && <Form.Item name={[f.name, "stdout"]} label={t("evolution.scriptStdout")}>
          <Input.TextArea rows={3} maxLength={16384} />
        </Form.Item>}
        <Form.Item name={[f.name, "fileCheck"]} valuePropName="checked"><Checkbox>{t("evolution.checkScriptFiles")}</Checkbox></Form.Item>
        {rules[f.name].fileCheck && <Form.Item name={[f.name,"files"]} label={t("evolution.expectedScriptFiles")}
          rules={[{validator: async (_,value) => {
            try {
              const obj = JSON.parse(value?.trim() || "{}");
              if (obj && typeof obj === "object" && !Array.isArray(obj) && Object.values(obj).every(v => typeof v === "string")) return;
            } catch { /* Report a localized form error. */ }
            throw new Error(t("evolution.expectedScriptFiles"));
          }}]}><Input.TextArea rows={2} placeholder={'{"report.txt":"..."}'}/></Form.Item>}
      </>}
      <Button onClick={() => remove(f.name)}>{t("evolution.removeToolRule")}</Button>
    </div>)}
    <Button disabled={fields.length >= 32} onClick={() => add({ min: 1 })}>{t("evolution.addToolRule")}</Button>
  </>}</Form.List>
    {!!rules?.length && <Form.Item name="toolOrder" label={t("evolution.toolOrder")}>
      <Input placeholder="read_skill_md, read_skill_config" />
    </Form.Item>}
  </>;
}
