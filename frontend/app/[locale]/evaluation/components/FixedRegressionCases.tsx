// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useState } from "react";
import { Alert, Button, Flex, Select } from "antd";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { evolutionService, type Workspace } from "@/services/evolutionService";

export default function FixedRegressionCases({ agent, version, workspace, refresh, rubrics, models }: {
  agent: number; version: number; workspace: Workspace; refresh: () => Promise<unknown>;
  rubrics: { evaluator_id: number; name: string; evaluator_type: string }[];
  models: { value: number; label: string }[];
}) {
  const { t, i18n } = useTranslation("common");
  const [selected, setSelected] = useState<number>();
  const [ruleId, setRule] = useState<number>();
  const [judge, setJudge] = useState<number>();
  const rule = rubrics.find(r => r.evaluator_id === ruleId);
  const needsModel = !!rule && rule.evaluator_type !== "code";
  const fixed = workspace.fixed_regression ?? [];
  const change = useMutation({
    mutationFn: ({ sourceVersion, id, enabled }: { sourceVersion: number; id: number; enabled: boolean }) =>
      evolutionService.setFixedRegression(agent, sourceVersion, id, enabled, enabled && rule ? {
        evaluator_id: rule.evaluator_id, language: i18n.language.startsWith("zh") ? "zh" : "en",
        judge_model_id: needsModel ? judge : undefined,
      } : undefined),
    onSuccess: async () => { setSelected(undefined); await refresh(); },
  });
  return <details><summary>{t("evolution.fixedSuite", { count: fixed.length })}</summary>
    <p>{t("evolution.fixedAutoInclude")}</p>
    {fixed.map(item => <Flex key={item.digest} gap={8} align="center">
      <span>{item.family} · {item.query} {item.rubric && `· ${item.rubric.name} V${item.rubric.version_no}`}</span>
      <Button size="small" disabled={change.isPending} onClick={() => change.mutate({
        sourceVersion: item.source_version, id: item.source_case_id, enabled: false,
      })}>{t("evolution.removeFixed")}</Button>
    </Flex>)}
    <Flex gap={8} wrap>
      <Select aria-label={t("evolution.chooseFixed")} placeholder={t("evolution.chooseFixed")}
        style={{ minWidth: 260 }} value={selected} onChange={setSelected} options={workspace.cases
          .filter(c => !fixed.some(f => f.digest === c.digest || f.source_case_id === c.case_id))
          .map(c => ({ value: c.case_id, label: `${c.family} · ${c.query}` }))} />
      <Select aria-label={t("evolution.fixedRubric")} placeholder={t("evolution.fixedRubric")} value={ruleId}
        style={{ minWidth: 160 }} onChange={setRule}
        options={rubrics.map(r => ({ value: r.evaluator_id, label: r.name }))} />
      {needsModel && <Select aria-label={t("evolution.fixedJudge")} placeholder={t("evolution.fixedJudge")}
        style={{ minWidth: 160 }} value={judge} onChange={setJudge} options={models} />}
      <Button disabled={!selected || !rule || (needsModel && !judge) || change.isPending} onClick={() => selected && change.mutate({
        sourceVersion: version, id: selected, enabled: true,
      })}>{t("evolution.addFixed")}</Button>
    </Flex>
    {change.error && <Alert type="error" message={change.error.message} />}
  </details>;
}
