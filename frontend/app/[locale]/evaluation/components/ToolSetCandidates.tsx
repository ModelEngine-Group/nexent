// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useState } from "react";
import { Alert, Button, Form, Select } from "antd";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { evolutionService as api, type ExperimentReport, type Workspace } from "@/services/evolutionService";

export default function ToolSetCandidates({ report, cases, onSelect }: {
  report: ExperimentReport; cases: Workspace["cases"]; onSelect: (id: number) => void;
}) {
  const { t } = useTranslation("common");
  const [failed, setFailed] = useState<number[]>([]);
  const [protectedIds, setProtected] = useState<number[]>([]);
  const mutation = useMutation({ mutationFn: () => api.toolSetCandidates(report.experiment_id, failed, protectedIds) });
  const options = (fail: boolean) => Object.entries(report.pairs).filter(([, pair]) => {
    const tool = pair.base.result?.tool_use;
    return fail ? pair.base.status === "fail" && tool?.issues?.some(i => i.reason === "too_many" && (i.max_calls ?? 0) === 0) :
      pair.base.status === "pass" && tool?.status === "pass";
  }).map(([id]) => ({ value: Number(id), label: cases.find(c => c.case_id === Number(id))?.query ?? id }));
  if (!options(true).length || !options(false).length) return null;
  return <details><summary>{t("evolution.proposeToolSets")}</summary>
    <Form layout="vertical">
      <Form.Item label={t("evolution.excessCalls")}>
        <Select aria-label={t("evolution.excessCalls")} mode="multiple" value={failed} options={options(true)}
          onChange={v => { setFailed(v); mutation.reset(); }} />
      </Form.Item>
      <Form.Item label={t("evolution.protectTools")}>
        <Select aria-label={t("evolution.protectTools")} mode="multiple" value={protectedIds} options={options(false)}
          onChange={v => { setProtected(v); mutation.reset(); }} />
      </Form.Item>
      <Button loading={mutation.isPending} disabled={!failed.length || !protectedIds.length}
        onClick={() => mutation.mutate()}>{t("evolution.generateToolSets")}</Button>
    </Form>
    {mutation.error && <Alert type="error" message={mutation.error.message} />}
    {mutation.data?.variants.map(v => <p key={v.candidate_id ?? "base"}>
      {v.candidate_id === null ? t("evolution.fullToolSet") : <>
        {t("evolution.removeTools", { names: v.removed.join(", ") })}{" "}
        <Button onClick={() => onSelect(v.candidate_id!)}>{t("evolution.tryToolSet")}</Button>
      </>}
    </p>)}
  </details>;
}
