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
  const callers = examples.filter(e => e.status === "pass");
  const callerForm = callers.length > 0 && <CallerApproval key={report.experiment_id} {...{agent,version,viewer,callers}}
    experiment={report.experiment_id}/>;
  if (!names.length) return callerForm || null;
  const options = (status: string) => examples.filter(e => e.name === name && e.status === status);
  return <>{callerForm}<details><summary>{t("evolution.submitToolRepair")}</summary>
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
  </details></>;
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
    {opened && brief.data && <><BuildRegistry key={opened} feedback={opened} viewer={viewer}/><p>{brief.data.tool_name} · {brief.data.goal}</p>
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

function BuildRegistry({feedback, viewer}: {feedback: number; viewer: string}) {
  const {t} = useTranslation("common");
  const [opened,setOpened] = useState(false);
  const [selected,select] = useState<number>();
  const ids = useQuery({queryKey:["tool-builds",viewer,feedback],queryFn:() => api.toolBuildIds(feedback),enabled:opened});
  const status = useQuery({queryKey:["tool-build-status",viewer,feedback,selected],
    queryFn:() => api.toolBuildStatus(selected!),enabled:opened && !!selected,retry:false});
  const save = useMutation({mutationFn:(body:Parameters<typeof api.registerToolBuild>[1]) => api.registerToolBuild(feedback,body),
    onSuccess:async data => {select(data.build_id); await ids.refetch();}});
  const image = [{required:true,pattern:/^sha256:[0-9a-f]{64}$/}];
  return <details onToggle={event => setOpened(event.currentTarget.open)}><summary>{t("evolution.build.registry")}</summary>
    <Form layout="vertical" initialValues={{port:8000,path:"/mcp",transport:"streamable-http"}} onFinish={v => save.mutate(v)}>
      <Form.Item name="base_image" label={t("evolution.build.base")} rules={image}><Input/></Form.Item>
      <Form.Item name="result_image" label={t("evolution.build.result")} rules={image}><Input/></Form.Item>
      <Form.Item name="review" label={t("evolution.build.review")} rules={[{required:true,whitespace:true}]}><Input.TextArea maxLength={1500}/></Form.Item>
      <Form.Item name="port" label={t("evolution.build.port")} rules={[{required:true}]}><InputNumber min={1} max={65535} precision={0}/></Form.Item>
      <Form.Item name="path" label={t("evolution.build.path")} rules={[{required:true}]}><Input/></Form.Item>
      <Form.Item name="transport" label={t("evolution.build.transport")}><Select options={["streamable-http","sse"].map(value => ({value}))}/></Form.Item>
      <Button htmlType="submit" loading={save.isPending}>{t("evolution.build.register")}</Button>
    </Form>
    <Select aria-label={t("evolution.build.id")} value={selected} onChange={select} style={{minWidth:140}}
      options={ids.data?.map(value => ({value,label:`#${value}`}))}/>
    <Button disabled={!selected} loading={status.isFetching} onClick={() => status.refetch()}>{t("evolution.build.refresh")}</Button>
    {[ids.error,status.error,save.error].map((e,i) => e && <Alert key={i} type="error" message={e.message}/>)}
    {status.data && <><p>{status.data.manifest.review}</p><code>{status.data.manifest.base_image} → {status.data.manifest.result_image}</code>
      <p>{t("evolution.build.coverage",{total:status.data.caller_count,missing:status.data.missing_caller_count,cases:status.data.case_count})}</p>
      <strong>{t(`evolution.build.${status.data.verification?.status ?? "pending"}`)}</strong>
      <ul>{status.data.verification?.cases.map(c => <li key={c.label}>{c.label} · {t(`evolution.build.${c.outcome}`)}</li>)}</ul></>}
  </details>;
}

function CallerApproval({agent,version,viewer,experiment,callers}: {agent:number;version:number;viewer:string;experiment:number;
  callers:{name:string;value:number;label:string}[]}) {
  const {t} = useTranslation("common");
  const [build,setBuild] = useState<number | null>(null);
  const [selected,select] = useState<string>();
  const [approved,approve] = useState(false);
  const target = callers.find(c => JSON.stringify([c.value,c.name]) === selected);
  const example = useApprovedExample(agent,version,viewer,target?.value,target?.name);
  const save = useMutation({mutationFn:() => api.approveToolCaller(build!,{experiment_id:experiment,
    case_id:target!.value,tool_name:target!.name,share_example:true})});
  return <details><summary>{t("evolution.build.contribute")}</summary>
    <InputNumber min={1} precision={0} aria-label={t("evolution.build.id")} placeholder={t("evolution.build.id")}
      value={build} onChange={v => {setBuild(v);approve(false);save.reset();}}/>
    <Select aria-label={t("evolution.feedback.protection")} value={selected} style={{minWidth:220}}
      onChange={v => {select(v);approve(false);save.reset();}} options={callers.map(c =>
        ({value:JSON.stringify([c.value,c.name]),label:c.name+" · "+c.label}))}/>
    {example.error && <Alert type="error" message={example.error.message}/>}
    {example.data && <pre>{JSON.stringify(example.data,null,2)}</pre>}
    <Checkbox checked={approved} disabled={!build || !example.data} onChange={e => approve(e.target.checked)}>{t("evolution.build.consent")}</Checkbox>
    <Button disabled={!approved || !build || !example.data} loading={save.isPending} onClick={() => save.mutate()}>{t("evolution.build.submit")}</Button>
    {save.error && <Alert type="error" message={save.error.message}/>}
    {save.data && <Alert type="success" message={t("evolution.build.saved")}/>}
  </details>;
}
