// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Checkbox, Flex, Form, Input, Radio, Select, Typography } from "antd";
import { useState } from "react";
import { useModelList } from "@/hooks/model/useModelList";
import { useTranslation } from "react-i18next";
import { evolutionService as api, type ExperimentReport, type ScriptFeedback, type Workspace } from "@/services/evolutionService";

function ApprovedScriptInput({ id, agent, version, viewer }: { id?: number; agent: number; version: number; viewer: string }) {
  const data = useQuery({ queryKey: ["feedback-case", viewer, agent, version, id], enabled: !!id,
    queryFn: () => api.developmentCase(agent, version, id!), retry: false });
  const rule = data.data?.task.tool_use?.rules.find(r => r.expected_script_stdout !== undefined || r.expected_script_files !== undefined);
  if (data.error) return <Alert type="error" message={data.error.message}/>;
  return rule ? <pre>{JSON.stringify({arguments: rule.arguments, expected_stdout: rule.expected_script_stdout, expected_files: rule.expected_script_files}, null, 2)}</pre> : null;
}

export function ScriptFeedbackForm({report, workspace, agent, version, viewer, onFeedback}: {
  report: ExperimentReport; workspace: Workspace; agent: number; version: number; viewer: string;
  onFeedback?: (id: number) => void;
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
  const save = useMutation({mutationFn:(data: ScriptFeedback) => api.shareScriptFeedback(report.experiment_id, data),
    onSuccess: ({ feedback_id }) => onFeedback?.(feedback_id)});
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

export function ScriptDraftForm({ feedbackId, onSelect }: {
  feedbackId: number; onSelect?: (id: number) => void;
}) {
  const queries = useQueryClient();
  const {availableLlmModels} = useModelList();
  const models = availableLlmModels.map(model => ({value: model.id, label: model.displayName || model.name}));
  const {t} = useTranslation("common");
  const [manual,setManual] = useState(false);
  const [code,setCode] = useState("");
  const [model,setModel] = useState<number>();
  const selectedModel = model ?? (models.length === 1 ? models[0].value : undefined);
  const draft = useMutation({mutationFn:() => api.scriptDraft(feedbackId, manual ? {replacement:code} : {model_id:selectedModel!})});
  const build = useMutation({mutationFn:() => {
    const reviewed = draft.data!;
    return api.buildScript(feedbackId, {replacement: reviewed.replacement, draft_digest: reviewed.draft_digest, source_digest: reviewed.source_digest});
  }, onSuccess: () => queries.invalidateQueries({queryKey: ["evolution"]})});
  const reset = () => { draft.reset(); build.reset(); };
  return <Flex vertical gap={12}>
    <Typography.Text>{t("evolution.workflow.scriptHelp")}</Typography.Text>
    <Form layout="vertical">
    <Radio.Group value={manual} onChange={e => {setManual(e.target.value); reset();}} options={[
      {label:t("evolution.scriptModel"), value:false},{label:t("evolution.scriptManual"),value:true}]}/>
    {manual ? <Form.Item label={t("evolution.scriptReplacement")}><Input.TextArea aria-label={t("evolution.scriptReplacement")} rows={6} maxLength={32768} value={code}
      onChange={e => {setCode(e.target.value); reset();}}/></Form.Item>
      : <Form.Item label={t("evolution.generatorModel")}><Select aria-label={t("evolution.generatorModel")}
        options={models} value={selectedModel} onChange={v => {setModel(v); reset();}}/></Form.Item>}
    <Button disabled={manual ? !code.trim() : !selectedModel} loading={draft.isPending} onClick={() => {build.reset(); draft.mutate();}}>{t("evolution.scriptDraft")}</Button>
  </Form>
    {draft.error && <Alert type="error" message={draft.error.message}/>}
    {draft.data && <><strong>{draft.data.script_path} · {draft.data.function}</strong><pre>{draft.data.diff}</pre>
      <Button disabled={build.isSuccess} loading={build.isPending} onClick={() => build.mutate()}>{t("evolution.reviewedBuild")}</Button>
      {build.error && <Alert type="error" message={build.error.message}/>}
      {build.data && <Flex gap={8} align="center" wrap>
        <Typography.Text>{t("evolution.scriptBuildCreated", {id:build.data.candidate_id})}</Typography.Text>
        {onSelect && <Button onClick={() => onSelect(build.data.candidate_id)}>{t("evolution.workflow.compareThis")}</Button>}
      </Flex>}</>}
  </Flex>;
}
