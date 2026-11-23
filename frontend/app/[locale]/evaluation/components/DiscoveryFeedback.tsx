// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useState } from "react";
import { Alert, Button, Form, Input, InputNumber, Select } from "antd";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useModelList } from "@/hooks/model/useModelList";
import { evolutionService as api, type ExperimentReport, type Workspace } from "@/services/evolutionService";

const groups = ["missed", "overused", "correct"] as const;
type Group = typeof groups[number];
type Fields = { goal: string } & Record<Group, { case_id: number; query_excerpt: string }>;

export default function DiscoveryFeedback({ report, workspace }: { report: ExperimentReport; workspace: Workspace }) {
  const { t } = useTranslation("common");
  const [skill, setSkill] = useState<number>();
  const [form] = Form.useForm<Fields>();
  const name = workspace.skills?.find(s => s.skill_id === skill)?.name;
  const submit = useMutation({
    mutationFn: async () => api.shareDiscovery(report.experiment_id, {
      ...await form.validateFields(), method: "S1", skill_id: skill!,
    }),
  });
  function casesFor(group: Group) {
    return workspace.cases.filter(c => {
      const base = report.pairs[String(c.case_id)]?.base;
      const selection = base?.result?.selection;
      if (!name || !selection || !["pass", "fail"].includes(base.status)) return false;
      const expected = selection.expected.includes(name);
      const read = name in selection.reads;
      if (group === "missed") return expected && !selection.expected.some(n => n in selection.reads);
      if (group === "overused") return !expected && read;
      return expected && read && selection.outcome === "hit" && base.status === "pass";
    });
  }
  return <details>
    <summary>{t("evolution.discoveryFeedback")}</summary>
    <Form layout="vertical" form={form}>
      <Form.Item label={t("evolution.targetSkill")}>
        <Select aria-label={t("evolution.targetSkill")} value={skill} onChange={id => { setSkill(id); form.resetFields(); submit.reset(); }}
          options={workspace.skills?.map(s => ({ value: s.skill_id, label: s.name }))} />
      </Form.Item>
      <Form.Item name="goal" label={t("evolution.discoveryGoal")} rules={[{ required: true, whitespace: true }]}>
        <Input maxLength={1500} />
      </Form.Item>
      {groups.map(group => <div key={group}>
        <Form.Item name={[group, "case_id"]} label={t(`evolution.group.${group}`)} rules={[{ required: true }]}>
          <Select options={casesFor(group).map(c => ({ value: c.case_id, label: c.query }))}
            onChange={id => form.setFieldValue([group, "query_excerpt"], workspace.cases.find(c => c.case_id === id)?.query)} />
        </Form.Item>
        <Form.Item name={[group, "query_excerpt"]} label={t("evolution.approvedExcerpt")} rules={[{ required: true, whitespace: true }]}>
          <Input.TextArea maxLength={1500} />
        </Form.Item>
      </div>)}
      <Button disabled={!skill} loading={submit.isPending} onClick={() => submit.mutate()}>{t("evolution.shareFeedback")}</Button>
    </Form>
    {submit.error && <Alert type="error" message={submit.error.message} />}
    {submit.data && <Alert type="success" message={t("evolution.feedbackCreated", { id: submit.data.feedback_id })} />}
  </details>;
}

export function ResourceCandidateGenerator() {
  const { t } = useTranslation("common");
  const { availableLlmModels } = useModelList();
  const [feedback, setFeedback] = useState<number | null>();
  const [model, setModel] = useState<number>();
  const generate = useMutation({ mutationFn: () => api.fromFeedback(feedback!, model!) });
  return <details>
    <summary>{t("evolution.generateFromFeedback")}</summary>
    <Form layout="inline">
      <Form.Item label={t("evolution.feedbackId")}><InputNumber min={1} precision={0} value={feedback}
        onChange={setFeedback} /></Form.Item>
      <Form.Item label={t("evolution.generatorModel")}><Select style={{ minWidth: 160 }} value={model} onChange={setModel}
        options={availableLlmModels.map(m => ({ value: m.id, label: m.displayName || m.name }))} /></Form.Item>
      <Button disabled={!feedback || !model} loading={generate.isPending} onClick={() => generate.mutate()}>
        {t("evolution.generateFromFeedback")}
      </Button>
    </Form>
    {generate.error && <Alert type="error" message={generate.error.message} />}
    {generate.data && <div><strong>#{generate.data.candidate_id} · {generate.data.method}</strong>
      <p><del>{generate.data.edit.old}</del></p><p><ins>{generate.data.edit.new}</ins></p></div>}
  </details>;
}
