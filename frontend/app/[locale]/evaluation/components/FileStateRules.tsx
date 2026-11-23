// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { Button, Form, Input, Select } from "antd";
import { useTranslation } from "react-i18next";
import type { FileStateCheck } from "@/services/evolutionService";

export type FileRule = { name: string; action: "create" | "edit" | "delete" | "protect" | "absent"; before?: string; after?: string };

export function fileStateRule(rows: FileRule[], duplicate: string): FileStateCheck {
  const initial = new Map<string, string>();
  const expected = new Map<string, string>();
  const names = new Set<string>();
  const protectedNames: string[] = [];
  for (const row of rows) {
    const name = row.name.trim();
    const key = name.toLowerCase();
    if (names.has(key)) throw new Error(duplicate);
    names.add(key);
    if (["edit", "delete", "protect"].includes(row.action)) initial.set(name, row.before || "");
    if (["edit", "create"].includes(row.action)) expected.set(name, row.after || "");
    if (row.action === "protect") expected.set(name, row.before || "");
    if (["protect", "absent"].includes(row.action)) protectedNames.push(name);
  }
  return { adapter: "text-files-v1", initial: Object.fromEntries(initial), expected: Object.fromEntries(expected), protected: protectedNames };
}

export default function FileStateRules() {
  const { t } = useTranslation("common");
  return <Form.List name="fileRules">{(fields, { add, remove }) => <>
    {fields.map(({ name, key }) => <div key={key}>
      <Form.Item name={[name, "name"]} label={t("evolution.fileName")} rules={[{ required: true, whitespace: true }]}>
        <Input maxLength={128} />
      </Form.Item>
      <Form.Item name={[name, "action"]} label={t("evolution.fileChange")}>
        <Select options={["create","edit","delete","protect","absent"].map(value => ({value,label:t(`evolution.fileAction.${value}`)}))} />
      </Form.Item>
      <Form.Item noStyle shouldUpdate>{({ getFieldValue }) => {
        const action = getFieldValue(["fileRules", name, "action"]) || "edit";
        return <>
          {["edit","delete","protect"].includes(action) && <Form.Item name={[name,"before"]} label={t("evolution.fileBefore")}>
            <Input.TextArea rows={2} />
          </Form.Item>}
          {["edit","create"].includes(action) && <Form.Item name={[name,"after"]} label={t("evolution.fileAfter")}>
            <Input.TextArea rows={2} />
          </Form.Item>}
        </>;
      }}</Form.Item>
      <Button onClick={() => remove(name)}>{t("evolution.removeFileRule")}</Button>
    </div>)}
    <Button disabled={fields.length >= 32} onClick={() => add({action:"edit"})}>{t("evolution.addFileRule")}</Button>
  </>}</Form.List>;
}
