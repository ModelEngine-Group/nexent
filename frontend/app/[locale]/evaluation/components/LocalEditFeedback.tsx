// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useState } from "react";
import { Alert, Button, Checkbox, Form, Input, Modal, Select } from "antd";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { evolutionService as api, type ExperimentReport, type LocalFeedback, type Workspace } from "@/services/evolutionService";

export default function LocalEditFeedback({ report, workspace, agent, version, viewer }: {
  report: ExperimentReport; workspace: Workspace; agent: number; version: number; viewer: string;
}) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm<LocalFeedback & { skill_target?: string }>();
  const method = Form.useWatch("method", form);
  const failed = Form.useWatch(["failure", "case_id"], form);
  const good = Form.useWatch(["protection", "case_id"], form);
  const tool = Form.useWatch("tool_name", form);
  const isTool = method === "T1" || method === "T2";
  const need = (status: string) => Object.entries(report.pairs).filter(([,p]) => p.base.status === status).map(([id]) => ({
    value: Number(id), label: workspace.cases.find(c => c.case_id === Number(id))?.query ?? id,
  }));
  const readCase = (id: number | undefined) => ({
    queryKey: ["feedback-case", viewer, agent, version, id], enabled: !!id && open,
    queryFn: () => api.developmentCase(agent, version, id!), retry: false,
  });
  const failure = useQuery(readCase(failed));
  const protection = useQuery(readCase(good));
  const checked = (id?: number) => report.pairs[String(id)]?.base.result?.tool_use?.checked || [];
  const tools = checked(failed).filter(name => checked(good).includes(name));
  const parameters = Object.keys(failure.data?.task.tool_use?.rules.find(r => r.name === tool)?.arguments || {});
  const fileChecks = isTool && !!report.pairs[String(failed)]?.base.result?.file_state &&
    !!report.pairs[String(good)]?.base.result?.file_state;
  const skillOptions = [
    ...(workspace.skills ?? []).map(s => ({ value: `catalog:${s.skill_id}`, label: s.name })),
    ...(workspace.released_guides ?? []).map(s => ({ value: `guide:${s.candidate_id}`, label: s.name })),
  ];
  const submit = useMutation({ mutationFn: async () => {
    const { skill_target, ...data } = await form.validateFields();
    const [targetKind, targetId] = (skill_target ?? "").split(":");
    return api.shareLocalEdit(report.experiment_id, {
      ...data, tool_name: isTool ? data.tool_name : undefined,
      skill_id: method === "S2" && targetKind === "catalog" ? Number(targetId) : undefined,
      released_guide_candidate_id: method === "S2" && targetKind === "guide" ? Number(targetId) : undefined,
      related_passage: method === "P3" ? data.related_passage?.trim() || undefined : undefined,
      failure: { ...data.failure, observed: data.failure.observed ?? "" },
      protection: { ...data.protection, observed: data.protection.observed ?? "" },
      share_expected_arguments: method === "T2" ? data.share_expected_arguments : undefined,
      share_file_state: fileChecks ? data.share_file_state : undefined,
    });
  }});
  if (!need("fail").length || !need("pass").length) return null;
  return <>
    <Button onClick={() => setOpen(true)}>{t("evolution.shareLocalEdit")}</Button>
    <Modal open={open} title={t("evolution.shareLocalEdit")} onCancel={() => setOpen(false)}
      okText={t("evolution.shareFeedback")} cancelText={t("common.cancel")} confirmLoading={submit.isPending}
      onOk={() => submit.mutate()} destroyOnHidden>
      <Form form={form} layout="vertical" initialValues={{ method: "P1" }} onValuesChange={() => submit.reset()}>
        <Form.Item name="method" label={t("evolution.editMethod")} rules={[{ required: true }]}>
          <Select options={["P1","P3","T1","T2","S2"].map(value => ({ value, label: t(`evolution.method.${value}`) }))}
            onChange={() => form.setFieldValue("share_file_state", false)} />
        </Form.Item>
        {method === "S2" && <Form.Item name="skill_target" preserve={false} label={t("evolution.targetSkill")} rules={[{ required: true }]}>
          <Select options={skillOptions} />
        </Form.Item>}
        <Form.Item name="goal" label={t("evolution.editGoal")} rules={[{ required: true, whitespace: true }]}><Input maxLength={1500} /></Form.Item>
        <Form.Item name="source_passage" label={t("evolution.sourcePassage")} rules={[{ required: true, whitespace: true }]}>
          <Input.TextArea maxLength={2000} rows={2} />
        </Form.Item>
        {method === "P3" && <Form.Item name="related_passage" label={t("evolution.relatedPromptPassage")} preserve={false}>
          <Input.TextArea maxLength={2000} rows={2} />
        </Form.Item>}
        {(["failure","protection"] as const).map(group => {
          const id = group === "failure" ? failed : good;
          const details = group === "failure" ? failure : protection;
          const answer = report.pairs[String(id)]?.base.result?.answer;
          return <div key={group}>
            <Form.Item name={[group,"case_id"]} label={t(`evolution.feedback.${group}`)} rules={[{ required: true }]}>
              <Select options={need(group === "failure" ? "fail" : "pass")} onChange={() => {
                for (const field of ["expected","observed","input_excerpt"] as const) form.setFieldValue([group,field], undefined);
                form.setFieldValue("tool_name", undefined);
                form.setFieldValue("share_expected_arguments", []);
                form.setFieldValue("share_file_state", false);
              }} />
            </Form.Item>
            {details.error && <Alert type="error" message={details.error.message} />}
            {details.data && <details><summary>{t("evolution.viewTaskEvidence")}</summary>
              <p>{details.data.task.query}</p><p>{details.data.task.expected}</p><p>{answer}</p>
            </details>}
            {(["input_excerpt","expected","observed"] as const).map(field =>
              <Form.Item key={field} name={[group,field]} label={t(`evolution.excerpt.${field}`)}
                rules={field === "input_excerpt" || field === "observed" && answer === "" ? [] : [{ required: true, whitespace: true }]}
                normalize={value => field === "input_excerpt" && !value ? undefined : value}>
                <Input.TextArea rows={1} maxLength={field === "input_excerpt" ? 1500 : 3000} />
              </Form.Item>)}
          </div>;
        })}
        {isTool && <Form.Item name="tool_name" label={t("evolution.toolName")} rules={[{ required: true }]}>
          <Select options={tools.map(value => ({ value, label: value }))} onChange={() => {
            form.setFieldValue("share_expected_arguments", []);
            form.setFieldValue("share_file_state", false);
          }} />
        </Form.Item>}
        {fileChecks && <Form.Item name="share_file_state" valuePropName="checked">
          <Checkbox>{t("evolution.shareFileChecks")}</Checkbox>
        </Form.Item>}
        {method === "T2" && !!parameters.length && <Form.Item name="share_expected_arguments" label={t("evolution.shareArgumentValues")}>
          <Select mode="multiple" options={parameters.map(value => ({ value, label: value }))} />
        </Form.Item>}
      </Form>
      {submit.error && <Alert type="error" message={submit.error.message} />}
      {submit.data && <Alert type="success" message={t("evolution.feedbackCreated", { id: submit.data.feedback_id })} />}
    </Modal>
  </>;
}
