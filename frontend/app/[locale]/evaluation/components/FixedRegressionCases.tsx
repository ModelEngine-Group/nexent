// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { useState } from "react";
import { Alert, Button, Checkbox, Flex, Modal, Select, Table, Tag, Typography } from "antd";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { evolutionService, type Workspace } from "@/services/evolutionService";

type BusinessCase = Workspace["cases"][number];
type RegressionCase = NonNullable<Workspace["fixed_regression"]>[number];

export default function FixedRegressionCases({
  agent, version, workspace, refresh, rubrics, models, suggestedEvaluator, suggestedJudge, onNewCase,
}: {
  agent: number;
  version: number;
  workspace: Workspace;
  refresh: () => Promise<unknown>;
  rubrics: { evaluator_id: number; name: string; evaluator_type: string }[];
  models: { value: number; label: string }[];
  suggestedEvaluator?: number;
  suggestedJudge?: number;
  onNewCase?: () => void;
}) {
  const { t, i18n } = useTranslation("common");
  const [onlyFixed, setOnlyFixed] = useState(false);
  const [adding, setAdding] = useState<BusinessCase>();
  const [ruleId, setRule] = useState<number>();
  const [judge, setJudge] = useState<number>();
  const rule = rubrics.find((item) => item.evaluator_id === ruleId);
  const needsJudge = !!rule && rule.evaluator_type !== "code";
  const fixed = workspace.fixed_regression ?? [];
  const rows: Array<{ key: string; family: string; query: string; task?: BusinessCase; member?: RegressionCase }> =
    workspace.cases.map((task) => ({
      key: `case-${task.case_id}`,
      family: task.family,
      query: task.query,
      task,
      member: fixed.find((member) => member.digest === task.digest ||
        (member.source_version === version && member.source_case_id === task.case_id)),
    }));
  const displayedDigests = new Set(rows.flatMap((row) => row.member ? [row.member.digest] : []));
  for (const member of fixed) {
    if (!displayedDigests.has(member.digest)) {
      rows.push({ key: member.digest, family: member.family, query: member.query, member });
    }
  }

  const change = useMutation({
    mutationFn: ({ sourceVersion, id, enabled }: { sourceVersion: number; id: number; enabled: boolean }) =>
      evolutionService.setFixedRegression(agent, sourceVersion, id, enabled, enabled && rule ? {
        evaluator_id: rule.evaluator_id,
        language: i18n.language.startsWith("zh") ? "zh" : "en",
        judge_model_id: needsJudge ? judge : undefined,
      } : undefined),
    onSuccess: async () => {
      setAdding(undefined);
      await refresh();
    },
  });

  const open = (task: BusinessCase) => {
    change.reset();
    setRule(rubrics.some((item) => item.evaluator_id === suggestedEvaluator)
      ? suggestedEvaluator : rubrics.length === 1 ? rubrics[0].evaluator_id : undefined);
    setJudge(models.some((item) => item.value === suggestedJudge)
      ? suggestedJudge : models.length === 1 ? models[0].value : undefined);
    setAdding(task);
  };

  return (
    <Flex vertical gap={12}>
      <Flex align="center" justify="space-between" gap={8} wrap>
        <Checkbox checked={onlyFixed} onChange={(event) => setOnlyFixed(event.target.checked)}>
          {t("evolution.fixedSuite", { count: fixed.length })}
        </Checkbox>
        {onNewCase && <Button type="primary" onClick={onNewCase}>{t("evolution.newCase")}</Button>}
      </Flex>
      <Typography.Text type="secondary">{t("evolution.fixedAutoInclude")}</Typography.Text>
      {!adding && change.error && <Alert showIcon type="error" message={change.error.message} />}
      <Table
        size="small"
        rowKey="key"
        dataSource={onlyFixed ? rows.filter((row) => row.member) : rows}
        pagination={rows.length > 10 ? { pageSize: 10, hideOnSinglePage: true } : false}
        columns={[
          {
            title: t("evolution.cases"),
            render: (_, row) => <Flex vertical gap={2}>
              <Typography.Text type="secondary">{row.family}</Typography.Text>
              <Typography.Text className="whitespace-pre-wrap break-words">{row.query}</Typography.Text>
            </Flex>,
          },
          {
            title: t("evolution.fixedRubric"),
            render: (_, { member }) => member?.rubric ? `${member.rubric.name} V${member.rubric.version_no}` : "—",
          },
          {
            title: t("evolution.workflow.caseAction"),
            render: (_, { member, task }) => member ? <Flex wrap gap={4} align="center">
              <Tag>{t("evolution.workflow.fixedTag")}</Tag>
              <Button disabled={change.isPending} size="small" type="link" onClick={() => change.mutate({
                id: member.source_case_id, sourceVersion: member.source_version, enabled: false,
              })}>{t("evolution.removeFixed")}</Button>
            </Flex> : task && <Button disabled={change.isPending} size="small" type="link" onClick={() => open(task)}>
              {t("evolution.addFixed")}
            </Button>,
          },
        ]}
      />
      <Modal
        centered
        open={!!adding}
        title={t("evolution.addFixed")}
        onCancel={() => { setAdding(undefined); change.reset(); }}
        cancelText={t("common.cancel")}
        okText={t("evolution.addFixed")}
        okButtonProps={{ disabled: !rule || (needsJudge && !judge) }}
        confirmLoading={change.isPending}
        closable={!change.isPending}
        keyboard={!change.isPending}
        mask={{ closable: false }}
        cancelButtonProps={{ disabled: change.isPending }}
        onOk={() => adding && change.mutate({ id: adding.case_id, sourceVersion: version, enabled: true })}
      >
        <Flex vertical gap={12}>
          <Typography.Paragraph>{adding?.query}</Typography.Paragraph>
          {!rubrics.length && <Alert showIcon type="info" message={t("evolution.workflow.publishEvaluator")} />}
          <Select aria-label={t("evolution.fixedRubric")} placeholder={t("evolution.fixedRubric")}
            value={ruleId} onChange={setRule} options={rubrics.map((item) => ({ value: item.evaluator_id, label: item.name }))} />
          {needsJudge && <Select aria-label={t("evolution.fixedJudge")} placeholder={t("evolution.fixedJudge")}
            value={judge} onChange={setJudge} options={models} />}
          {change.error && <Alert showIcon type="error" message={change.error.message} />}
        </Flex>
      </Modal>
    </Flex>
  );
}
