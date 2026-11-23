// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, Button, Checkbox, Form, Input, InputNumber, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { evolutionService as api, type ExperimentReport, type ToolRepairFeedback, type Workspace } from "@/services/evolutionService";

function useApprovedExample(agent: number, version: number, viewer: string, id?: number, tool?: string) {
  const example = useQuery({queryKey:["feedback-case", viewer, agent, version, id], enabled: !!id,
    queryFn:() => api.developmentCase(agent, version, id!), retry:false});
  const rule = example.data?.task.tool_use?.rules.find(r => r.name === tool && r.expected_mcp_reply?.fixture);
  return {data: rule && {arguments:rule.arguments, expected:rule.expected_mcp_reply}, error:example.error};
}

export function ToolRepairForm({report, workspace, agent, version, viewer}: {
  report: ExperimentReport; workspace: Workspace; agent: number; version: number; viewer: string;
}) {
  const {t} = useTranslation("common");
  const [form] = Form.useForm<ToolRepairFeedback>();
  const name = Form.useWatch("tool_name",form);
  const failure = Form.useWatch("failure_case_id",form);
  const protection = Form.useWatch("protection_case_id",form);
  const failedExample = useApprovedExample(agent,version,viewer,failure,name);
  const normalExample = useApprovedExample(agent,version,viewer,protection,name);
  const canShare = !!failedExample.data && !!normalExample.data && !failedExample.error && !normalExample.error;
  const save = useMutation({mutationFn:(data:ToolRepairFeedback) => api.shareToolRepair(report.experiment_id,data)});
  const examples = workspace.cases.flatMap(c => {
    const trial = report.pairs[String(c.case_id)]?.base;
    return (trial?.result?.tool_use?.mcp_evidence ?? []).filter(e => e.input_matches && e.state_matches != null &&
      (trial?.status === "fail" ? !e.reply_matches || !e.state_matches : trial?.status === "pass" && e.reply_matches && e.state_matches))
      .map(e => ({name:e.tool, status:trial!.status, value:c.case_id, label:c.query}));
  });
  const names = [...new Set(examples.filter(e => e.status === "fail").map(e => e.name))].filter(n =>
    examples.some(e => e.name === n && e.status === "pass"));
  if (!names.length) return null;
  const options = (status: string) => examples.filter(e => e.name === name && e.status === status);
  return <details><summary>{t("evolution.submitToolRepair")}</summary>
    <Form layout="vertical" form={form} onFinish={v => save.mutate(v)} onValuesChange={changed => {
      save.reset();
      if ("tool_name" in changed) form.resetFields(["failure_case_id","protection_case_id"]);
      if (["tool_name","failure_case_id","protection_case_id"].some(key => key in changed)) form.setFieldValue("share_tool_examples",false);
    }}>
      <Form.Item name="tool_name" label={t("evolution.toolName")} rules={[{required:true}]}>
        <Select options={names.map(n => ({value:n,label:n}))}/></Form.Item>
      <Form.Item name="failure_case_id" label={t("evolution.feedback.failure")} rules={[{required:true}]}><Select options={options("fail")}/></Form.Item>
      {failedExample.error && <Alert type="error" message={failedExample.error.message}/>}
      {failedExample.data && <pre>{JSON.stringify(failedExample.data,null,2)}</pre>}
      <Form.Item name="protection_case_id" label={t("evolution.feedback.protection")} rules={[{required:true}]}><Select options={options("pass")}/></Form.Item>
      {normalExample.error && <Alert type="error" message={normalExample.error.message}/>}
      {normalExample.data && <pre>{JSON.stringify(normalExample.data,null,2)}</pre>}
      <Form.Item name="repeat_experiment_id" label={t("evolution.scriptRepeat")} rules={[{required:true}]}>
        <Select options={workspace.experiments.filter(e => e.experiment_id !== report.experiment_id).map(e => ({value:e.experiment_id,label:`#${e.experiment_id}`}))}/></Form.Item>
      <Form.Item name="goal" label={t("evolution.editGoal")} rules={[{required:true,whitespace:true}]}><Input.TextArea maxLength={1500}/></Form.Item>
      <Form.Item name="share_tool_examples" valuePropName="checked" rules={[{validator:(_,v) => v ? Promise.resolve() :
        Promise.reject(new Error(t("evolution.shareToolExamples")))}]}><Checkbox disabled={!canShare}>{t("evolution.shareToolExamples")}</Checkbox></Form.Item>
      <Button htmlType="submit" disabled={!canShare} loading={save.isPending}>{t("evolution.submitToolRepair")}</Button>
    </Form>
    {save.error && <Alert type="error" message={save.error.message}/>}
    {save.data && <Alert type="success" message={t("evolution.feedbackCreated",{id:save.data.feedback_id})}/>}
  </details>;
}

export function ToolMaintainerBrief({viewer}: {viewer: string}) {
  const {t} = useTranslation("common");
  const [id, setId] = useState<number | null>(null);
  const [opened, open] = useState<number | null>(null);
  const brief = useQuery({queryKey:["tool-repair-brief",viewer,opened], queryFn:() => api.toolRepairBrief(opened!), enabled:!!opened, retry:false});
  return <details><summary>{t("evolution.toolRepairBrief")}</summary>
    <InputNumber aria-label={t("evolution.feedbackId")} value={id} min={1} precision={0} onChange={v => {setId(v); open(null);}}/>
    <Button disabled={!id} loading={brief.isFetching} onClick={() => open(id)}>{t("evolution.toolRepairBrief")}</Button>
    {brief.error && <Alert type="error" message={brief.error.message}/>}
    {opened && brief.data && <><p>{brief.data.tool_name} · {brief.data.goal}</p>
      <Button onClick={() => {
        const blob = new Blob([JSON.stringify(brief.data!.test_suite, null, 2)], {type:"application/json"});
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `tool-repair-${opened}.json`;
        link.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }}>{t("evolution.exportToolRepair")}</Button>
      {(["failure","protection"] as const).map(key => <div key={key}><strong>{t(`evolution.feedback.${key}`)}</strong>
        <pre>{JSON.stringify({arguments:brief.data![key].arguments, expected:brief.data![key].expected},null,2)}</pre></div>)}</>}
  </details>;
}
