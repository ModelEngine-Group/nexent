// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useMutation } from "@tanstack/react-query";
import { Alert, Button, Form, Input, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { evolutionService as api, type ExperimentReport, type Workspace } from "@/services/evolutionService";

export default function ToolMappingCandidate({report, cases, onSelect}: {
  report: ExperimentReport; cases: Workspace["cases"]; onSelect: (candidate: number) => void;
}) {
  const {t} = useTranslation("common");
  const [selected, setSelected] = useState<string>();
  const [guard, setGuard] = useState<number>();
  const [raw, setRaw] = useState("");
  const evidence = Object.entries(report.pairs).flatMap(([id, pair]) =>
    (pair.base.result?.tool_use?.argument_evidence ?? []).filter(e => !!e.requested && e.requested === e.effective)
      .map(e => ({...e, id: Number(id), status: pair.base.status, key: JSON.stringify([id, e.tool, e.field, e.call])})));
  const failed = evidence.filter(e => e.status === "fail" && e.effective !== e.expected);
  const target = failed.find(e => e.key === selected);
  const protectedIds = new Set(evidence.filter(e => e.status === "pass" && e.tool === target?.tool &&
    e.field === target?.field && e.effective === e.expected).map(e => e.id));
  const mutation = useMutation({mutationFn: () => api.toolMappingCandidate(report.experiment_id, {
    failure_case_id: target!.id, protection_case_id: guard!, tool_name: target!.tool, field: target!.field, supplied_value: raw,
  })});
  if (!failed.length) return null;
  return <details><summary>{t("evolution.mapping.title")}</summary>
    <Form layout="vertical">
      <Form.Item label={t("evolution.mapping.target")}>
        <Select aria-label={t("evolution.mapping.target")} value={selected} options={failed.map(e => ({
          value: e.key, label: `${cases.find(c => c.case_id === e.id)?.query ?? e.id} · ${e.tool}.${e.field}`,
        }))} onChange={v => {setSelected(v); setGuard(undefined); setRaw(""); mutation.reset();}}/>
      </Form.Item>
      <Form.Item label={t("evolution.mapping.raw")}>
        <Input aria-label={t("evolution.mapping.raw")} maxLength={512} value={raw}
          onChange={e => {setRaw(e.target.value); mutation.reset();}}/>
      </Form.Item>
      <Form.Item label={t("evolution.protectTools")}>
        <Select aria-label={t("evolution.protectTools")} value={guard}
          options={cases.filter(c => protectedIds.has(c.case_id)).map(c => ({value: c.case_id, label:c.query}))}
          onChange={v => {setGuard(v); mutation.reset();}}/>
      </Form.Item>
      <Button disabled={!target || !protectedIds.has(guard ?? -1) || !raw} loading={mutation.isPending}
        onClick={() => mutation.mutate()}>{t("evolution.mapping.generate")}</Button>
    </Form>
    {mutation.error && <Alert type="error" message={mutation.error.message}/>}
    {mutation.data && <p>{mutation.data.tool}.{mutation.data.field} · {t(`evolution.mapping.${mutation.data.rule.kind}`)}
      {" "}<Button onClick={() => onSelect(mutation.data.candidate_id)}>{t("evolution.mapping.try")}</Button></p>}
  </details>;
}
