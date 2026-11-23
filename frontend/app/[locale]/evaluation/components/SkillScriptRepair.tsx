// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, Button, Checkbox, Form, Input, InputNumber, Radio, Select } from "antd";
import { useState } from "react";
import { useModelList } from "@/hooks/model/useModelList";
import { useTranslation } from "react-i18next";
import { evolutionService as api, type ExperimentReport, type ScriptFeedback, type Workspace } from "@/services/evolutionService";

function ApprovedScriptInput({ id, agent, version, viewer }: { id?: number; agent: number; version: number; viewer: string }) {
  const data = useQuery({ queryKey: ["feedback-case", viewer, agent, version, id], enabled: !!id,
    queryFn: () => api.developmentCase(agent, version, id!), retry: false });
  const rule = data.data?.task.tool_use?.rules.find(r => r.expected_script_stdout !== undefined);
  if (data.error) return <Alert type="error" message={data.error.message}/>;
  return rule ? <pre>{JSON.stringify({arguments: rule.arguments, expected_stdout: rule.expected_script_stdout}, null, 2)}</pre> : null;
}

export function ScriptFeedbackForm({report, workspace, agent, version, viewer}: {
  report: ExperimentReport; workspace: Workspace; agent: number; version: number; viewer: string;
}) {
  const {t} = useTranslation("common");
  const [form] = Form.useForm<ScriptFeedback>();
  const failure = Form.useWatch("failure_case_id", form);
  const protection = Form.useWatch("protection_case_id", form);
  const options = (status: string) => workspace.cases.filter(c => {
    const trial = report.pairs[String(c.case_id)]?.base;
    const processes = trial?.result?.tool_use?.script_evidence;
    return trial?.status === status && processes?.length === 1 && processes[0].input_matches;
  }).map(c => ({value:c.case_id, label:c.query}));
  const save = useMutation({mutationFn:(data: ScriptFeedback) => api.shareScriptFeedback(report.experiment_id, data)});
  if (!options("fail").length || !options("pass").length) return null;
  return <details><summary>{t("evolution.scriptFeedback")}</summary>
    <Form layout="vertical" form={form} onFinish={v => save.mutate(v)} onValuesChange={(changed) => {
      if ("failure_case_id" in changed || "protection_case_id" in changed) form.setFieldValue("share_script_examples", false);
      save.reset();
    }}>
      <Form.Item name="failure_case_id" label={t("evolution.feedback.failure")} rules={[{required:true}]}><Select options={options("fail")}/></Form.Item>
      <ApprovedScriptInput id={failure} agent={agent} version={version} viewer={viewer}/>
      <Form.Item name="protection_case_id" label={t("evolution.feedback.protection")} rules={[{required:true}]}><Select options={options("pass")}/></Form.Item>
      <ApprovedScriptInput id={protection} agent={agent} version={version} viewer={viewer}/>
      <Form.Item name="repeat_experiment_id" label={t("evolution.scriptRepeat")} rules={[{required:true}]}>
        <Select options={workspace.experiments.filter(e => e.experiment_id !== report.experiment_id)
          .map(e => ({value:e.experiment_id, label:`#${e.experiment_id}`}))}/>
      </Form.Item>
      <Form.Item name="skill_id" label="Skill" rules={[{required:true}]}>
        <Select options={(workspace.skills ?? []).map(s => ({value:s.skill_id, label:s.name}))}/>
      </Form.Item>
      <Form.Item name="function" label={t("evolution.scriptFunction")} rules={[{required:true}]}><Input maxLength={128}/></Form.Item>
      <Form.Item name="goal" label={t("evolution.editGoal")} rules={[{required:true, whitespace:true}]}><Input.TextArea maxLength={1500}/></Form.Item>
      <Form.Item name="share_script_examples" valuePropName="checked" rules={[{validator:(_,v) =>
        v ? Promise.resolve() : Promise.reject(new Error(t("evolution.shareScriptExamples")))}]}>
        <Checkbox>{t("evolution.shareScriptExamples")}</Checkbox>
      </Form.Item>
      <Button htmlType="submit" loading={save.isPending}>{t("evolution.scriptFeedback")}</Button>
    </Form>
    {save.error && <Alert type="error" message={save.error.message}/>}
    {save.data && <Alert type="success" message={t("evolution.feedbackCreated", {id:save.data.feedback_id})}/>}
  </details>;
}

export function ScriptDraftForm() {
  const {availableLlmModels} = useModelList();
  const models = availableLlmModels.map(model => ({value: model.id, label: model.displayName || model.name}));
  const {t} = useTranslation("common");
  const [id,setId] = useState<number | null>(null);
  const [manual,setManual] = useState(false);
  const [code,setCode] = useState("");
  const [model,setModel] = useState<number>();
  const draft = useMutation({mutationFn:() => api.scriptDraft(id!, manual ? {replacement:code} : {model_id:model!})});
  return <details><summary>{t("evolution.scriptDraft")}</summary><Form layout="vertical">
    <Form.Item label={t("evolution.feedbackId")}><InputNumber aria-label={t("evolution.feedbackId")} value={id} min={1} precision={0} onChange={v => {setId(v); draft.reset();}}/></Form.Item>
    <Radio.Group value={manual} onChange={e => {setManual(e.target.value); draft.reset();}} options={[
      {label:t("evolution.scriptModel"), value:false},{label:t("evolution.scriptManual"),value:true}]}/>
    {manual ? <Form.Item label={t("evolution.scriptReplacement")}><Input.TextArea aria-label={t("evolution.scriptReplacement")} rows={6} maxLength={32768} value={code}
      onChange={e => {setCode(e.target.value); draft.reset();}}/></Form.Item>
      : <Form.Item label={t("evolution.scriptModel")}><Select options={models} value={model} onChange={v => {setModel(v); draft.reset();}}/></Form.Item>}
    <Button disabled={!id || (manual ? !code.trim() : !model)} loading={draft.isPending} onClick={() => draft.mutate()}>{t("evolution.scriptDraft")}</Button>
  </Form>
    {draft.error && <Alert type="error" message={draft.error.message}/>}
    {draft.data && <><strong>{draft.data.script_path} · {draft.data.function}</strong><pre>{draft.data.diff}</pre></>}
  </details>;
}
