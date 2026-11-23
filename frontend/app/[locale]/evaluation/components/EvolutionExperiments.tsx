// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useRef, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Flex,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Table,
  Typography,
} from "antd";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useModelList } from "@/hooks/model/useModelList";
import { evolutionService as api, type Trial, type TraceCaseDraft, type ScreeningCriteria } from "@/services/evolutionService";
import { storageService } from "@/services/storageService";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import ExampleCandidates from "./ExampleCandidates";
import DiscoveryFeedback, { ResourceCandidateGenerator } from "./DiscoveryFeedback";
import ToolUseRules, { toolExpectation, type ToolRuleFields } from "./ToolUseRules";
import FileStateRules, { fileStateRule, type FileRule } from "./FileStateRules";
import LocalEditFeedback from "./LocalEditFeedback";
import NewSkillBriefForm from "./NewSkillBriefForm";
import ToolSetCandidates from "./ToolSetCandidates";
import FixedRegressionCases from "./FixedRegressionCases";

function CaseForm({
  agent,
  version,
  skills,
  draft,
  close,
  saved,
}: {
  agent: number;
  version: number;
  skills: { name: string }[];
  draft?: TraceCaseDraft;
  close: () => void;
  saved: (id: number) => void;
}) {
  const { t } = useTranslation("common");
  const [files, setFiles] = useState<File[]>([]);
  const [labelSkill, setLabelSkill] = useState(false);
  const [expectedSkills, setExpectedSkills] = useState<string[]>([]);
  const [reviewed, setReviewed] = useState(false);
  const [stateless, setStateless] = useState(false);
  const [verifyFiles, setVerifyFiles] = useState(false);
  const [unused, setUnused] = useState<number[]>([]);
  const [purpose, setPurpose] = useState<"reproduce" | "protect">("reproduce");
  const [form] = Form.useForm<ToolRuleFields & {
    family: string;
    fileRules?: FileRule[];
    source_group?: string;
    query: string;
    expected: string;
    followups?: { query: string; attachment_names?: string[] }[];
  }>();
  const mutation = useMutation({
    mutationFn: async () => {
      const values = await form.validateFields();
      const { toolRules, toolOrder, fileRules, ...business } = values;
      const uploaded = files.length
        ? await storageService.uploadFiles(files)
        : undefined;
      if (
        uploaded &&
        (uploaded.failed_count || uploaded.results.length !== files.length)
      ) {
        throw new Error(t("evolution.attachmentFailed"));
      }
      const attachments =
        uploaded?.results.map((file, i) => ({
          name: files[i].name,
          object_name: file.object_name,
        })) || [];
      return api.createCase({
        ...business,
        tool_use: toolExpectation({ toolRules, toolOrder }),
        file_state: verifyFiles ? fileStateRule(fileRules || [], t("evolution.duplicateFile")) : undefined,
        source_group: values.source_group?.trim() || undefined,
        agent_id: agent,
        version_no: version,
        attachments,
        expected_skill_names: labelSkill ? expectedSkills : undefined,
        trace: draft && { turn_id: draft.turn_id, draft_digest: draft.draft_digest, purpose,
          inputs_reviewed: true, tools_require_no_reset: stateless, unused_attachment_slots: unused,
          use_previous_task: !!draft.correction_trajectory_id,
          ...(draft.preceding_turns ? { preceding_turns: draft.preceding_turns } : {}) },
      });
    },
    onSuccess: (response) => saved(response.case_id),
  });
  return (
    <Modal
      open
      title={t("evolution.newCase")}
      onCancel={close}
      onOk={() => mutation.mutate()}
      confirmLoading={mutation.isPending}
      okButtonProps={{ disabled: !!draft && (!reviewed || draft.attachment_count == null ||
        files.length + unused.length < draft.attachment_count || (draft.tool_count > 0 && !stateless && !verifyFiles)) }}
      okText={t("evolution.saveCase")}
      cancelText={t("common.cancel")}
    >
      <Form form={form} layout="vertical" initialValues={{ query: draft?.query || "",
        followups: draft?.segments?.slice(1).map(turn => ({ query: turn.query || "" })) }}>
        {draft && <>
          <p>{t("evolution.traceSource", { id: draft.trajectory_id, files: draft.attachment_count ?? "?",
            calls: draft.tool_count })}</p>
          {draft.query === null && <p>{t("evolution.traceRedactedBrief")}</p>}
          {draft.segments && <ol>{draft.segments.map(turn => <li key={turn.task_turn_id}>
            {t("evolution.turnSource", { id: turn.task_turn_id, files: turn.attachment_count ?? "?" })}
          </li>)}</ol>}
          {draft.correction_trajectory_id && <p>{t("evolution.traceCorrection", {
            evidence: draft.correction_query || draft.correction_trajectory_id,
          })}</p>}
          {!!draft.tools.length && <details><summary>{t("evolution.traceToolRefs", {
            count: draft.tools.length, total: draft.tool_count,
          })}</summary><ul>{draft.tools.map(tool => <li key={tool.node}>
            <code>{tool.node}</code>{tool.invocation_id && <> · <code>{tool.invocation_id}</code></>}
          </li>)}</ul></details>}
          {!!draft.attachment_count && <Form.Item label={t("evolution.unusedSourceFiles")}>
            <Select mode="multiple" aria-label={t("evolution.unusedSourceFiles")} value={unused} onChange={setUnused}
              options={Array.from({length: Math.min(draft.attachment_count, 32)}, (_, i) => ({
                value: i + 1, label: `#${i + 1} ${draft.attachment_names?.[i] || ""}`,
              }))} />
          </Form.Item>}
          <Select aria-label={t("evolution.tracePurpose")} value={purpose} onChange={setPurpose}
            options={["reproduce", "protect"].map(value => ({value, label: t(`evolution.tracePurpose.${value}`)}))} />
          {!!draft.tool_count && !verifyFiles && <p><Checkbox checked={stateless} onChange={e => setStateless(e.target.checked)}>
            {t("evolution.traceStateless")}</Checkbox></p>}
        </>}
        {(["family", "query", "expected"] as const).map((field) => (
          <Form.Item
            key={field}
            name={field}
            label={t(`evolution.${field}`)}
            rules={[{ required: true, whitespace: true }]}
          >
            {field === "family" ? (
              <Input maxLength={128} />
            ) : (
              <Input.TextArea rows={3} maxLength={16000} />
            )}
          </Form.Item>
        ))}
        <Form.Item label={t("evolution.sourceGroup")} name="source_group">
          <Input maxLength={128} />
        </Form.Item>
        <Checkbox checked={labelSkill} onChange={e => setLabelSkill(e.target.checked)}>{t("evolution.labelSkill")}</Checkbox>
        {labelSkill && <Form.Item label={t("evolution.acceptableSkills")}>
          <Select mode="multiple" value={expectedSkills} onChange={setExpectedSkills}
            options={skills.map(s => ({ value: s.name, label: s.name }))} />
        </Form.Item>}
        <ToolUseRules />
        <p><Checkbox checked={verifyFiles} onChange={e => { setVerifyFiles(e.target.checked); setStateless(false); }}>
          {t("evolution.verifyFiles")}</Checkbox></p>
        {verifyFiles && <FileStateRules />}
        <Form.Item label={t("evolution.attachments")}>
          <input
            type="file"
            multiple
            onChange={(e) => setFiles(Array.from(e.target.files || []))}
          />
        </Form.Item>
        <Form.List name="followups">
          {(fields, { add, remove }) => <>
            {fields.map(({ key, name }) => <div key={key}>
              <Form.Item name={[name, "query"]} label={t("evolution.followup", { turn: name + 2 })}
                rules={[{ required: true, whitespace: true }]}>
                <Input.TextArea rows={2} maxLength={16000} />
              </Form.Item>
              {files.length > 0 && <Form.Item name={[name, "attachment_names"]} label={t("evolution.followupFiles")}>
                <Select mode="multiple" options={files.map(file => ({ value: file.name, label: file.name }))} />
              </Form.Item>}
              {!draft?.segments && <Button onClick={() => remove(name)}>{t("evolution.removeTurn")}</Button>}
            </div>)}
            {!draft?.segments && <Button disabled={fields.length >= 15} onClick={() => add()}>{t("evolution.addTurn")}</Button>}
          </>}
        </Form.List>
        {draft && <Checkbox checked={reviewed} onChange={e => setReviewed(e.target.checked)}>
          {t("evolution.traceApproval")}</Checkbox>}
      </Form>
      {mutation.error instanceof Error && (
        <Alert type="error" message={mutation.error.message} />
      )}
    </Modal>
  );
}

function Experiments({
  agent,
  version,
  viewer,
}: {
  agent: number;
  version: number;
  viewer: string;
}) {
  const { t, i18n } = useTranslation("common");
  const { availableLlmModels } = useModelList();
  const [caseIds, setCases] = useState<number[]>([]);
  const [screen, setScreen] = useState(false);
  const [metric, setMetric] = useState<ScreeningCriteria["metric"]>("tasks_fixed");
  const [minimum, setMinimum] = useState<number | null>(1);
  const [targets, setTargets] = useState<number[]>([]);
  const [candidate, setCandidate] = useState<string>();
  const [sourceIds, setSources] = useState<number[]>([]);
  const [suggestion, setSuggestion] = useState<number>();
  const [targetCase, setTargetCase] = useState<number>();
  const [evaluatorId, setEvaluator] = useState<number>();
  const [judge, setJudge] = useState<number>();
  const [selected, setSelected] = useState<number>();
  const [adding, setAdding] = useState<boolean | number>(false);
  const [previousTask, setPreviousTask] = useState(false);
  const [preceding, setPreceding] = useState(0);
  const source = useQuery({
    queryKey: ["evolution-trace-case", viewer, agent, version, adding, previousTask, preceding],
    enabled: typeof adding === "number", retry: false, gcTime: 0,
    queryFn: () => api.traceCaseDraft(agent, version, Number(adding), previousTask, preceding),
  });
  const previous = useRef({ selection: "", key: "" });
  const workspace = useQuery({
    queryKey: ["evolution", viewer, agent, version],
    queryFn: () => api.workspace(agent, version),
    retry: false,
  });
  const rules = useQuery({
    queryKey: ["evolution-evaluators", viewer],
    queryFn: api.evaluators,
  });
  const needsJudge =
    rules.data?.find((item) => item.evaluator_id === evaluatorId)
      ?.evaluator_type !== "code";
  const report = useQuery({
    queryKey: ["experiment-report", viewer, selected],
    queryFn: () => api.report(selected!),
    enabled: !!selected,
    retry: false,
    refetchInterval: (query) =>
      ["pending", "running"].includes(query.state.data?.status || "")
        ? 2000
        : false,
  });
  const start = useMutation({
    mutationFn: () => {
      const [kind, id] = candidate!.split(":");
      const components = kind === "combination" ? sourceIds.map(selectedId => {
        const source = workspace.data!.experiments.find(e => e.experiment_id === selectedId)!;
        return { experiment_id: selectedId, candidate_type: source.candidate_type!, candidate_id: source.candidate_id! };
      }) : undefined;
      const params = {
        agent_id: agent,
        version_no: version,
        candidate_type: kind,
        components,
        candidate_id: id ? Number(id) : undefined,
        suggestion_id: suggestion,
        suggestion_target_case_id: suggestion ? targetCase : undefined,
        case_ids: caseIds,
        screening: screen && kind !== "baseline" ? { metric, minimum: minimum!, target_case_ids: targets } : undefined,
        evaluator_id: evaluatorId!,
        judge_model_id: needsJudge ? judge : undefined,
        language: i18n.language.startsWith("zh") ? "zh" : "en",
      };
      const selection = JSON.stringify(params);
      if (previous.current.selection !== selection)
        previous.current = { selection, key: crypto.randomUUID() };
      return api.submit({ ...params, request_id: previous.current.key });
    },
    onSuccess: (result) => {
      previous.current.selection = "";
      setSelected(result.experiment_id);
      void workspace.refetch();
    },
  });
  const cancel = useMutation({
    mutationFn: () => api.cancel(selected!),
    onSuccess: () => {
      void report.refetch();
    },
  });
  const nomination = useMutation({ mutationFn: (id: number) => api.nominate(id) });
  const confirmations = useQuery({
    queryKey: ["confirmation-results", viewer, agent, version, selected],
    queryFn: () => api.confirmationResults(selected!),
    enabled: !!selected && report.data?.screening?.status === "eligible",
    retry: false,
    refetchInterval: query => query.state.data?.some(row => !row.summary) ? 10000 : false,
  });
  const choices = workspace.data;
  const eligible = choices?.experiments.filter(e => e.eligible_component && e.candidate_type && e.candidate_id) || [];
  const fixedIds = new Set(report.data?.fixed_regression?.case_ids ?? []);
  const fixedDigests = new Set(choices?.fixed_regression?.map(c => c.digest));
  choices?.cases.forEach(c => { if (c.digest && fixedDigests.has(c.digest)) fixedIds.add(c.case_id); });
  const development = report.data && { ...report.data, pairs: Object.fromEntries(
    Object.entries(report.data.pairs).filter(([id]) => !fixedIds.has(Number(id)))) };
  const proposed = choices?.candidates.find(c => c.kind === "skill_new" && candidate === `skill_new:${c.candidate_id}`);
  const discoveryRun = candidate?.startsWith("skill_discovery:") || !!proposed;
  const scopeLabels = new Set(choices?.cases.filter(c => caseIds.includes(c.case_id) &&
    !fixedDigests.has(c.digest ?? "") && c.expected_skill_names != null).map(c => c.expected_skill_names!.includes(proposed?.name ?? "")));
  const baselineReport = report.data?.total_pairs === 0;
  const active = ["pending", "running"].includes(report.data?.status || "");
  const error =
    workspace.error ||
    rules.error ||
    start.error ||
    report.error ||
    cancel.error || confirmations.error;
  return (
    <Flex vertical gap={14}>
      {error instanceof Error && (
        <Alert type="error" showIcon message={error.message} />
      )}
      {choices && (
        <>
          {candidate !== "combination" && !!choices.suggestions?.length && (
            <Select
              allowClear
              aria-label={t("evolution.suggestion")}
              placeholder={t("evolution.suggestion")}
              value={suggestion}
              onChange={(id) => {
                setSuggestion(id);
                setTargetCase(undefined);
              }}
              options={choices.suggestions.map((item) => ({
                value: item.suggestion_id,
                label: `S-${item.suggestion_id} · ${item.expected_behavior}`,
              }))}
            />
          )}
          <FixedRegressionCases agent={agent} version={version} workspace={choices} refresh={workspace.refetch}
            rubrics={(rules.data || []).filter(r => r.status === "PUBLISHED")}
            models={availableLlmModels.map(m => ({ value: m.id, label: m.displayName || m.name }))} />
          {!!choices.reviews?.length && (
            <details>
              <summary>{t("evolution.recentObservations")}</summary>
              <label>{t("evolution.includePrevious")} <Select aria-label={t("evolution.includePrevious")}
                value={preceding} onChange={setPreceding} options={Array.from({length: 16}, (_, n) => ({value:n,label:n}))} /></label>
              <ul>
                {choices.reviews.map((row) => (
                  <li key={row.turn_id}>
                    #{row.turn_id} · {row.batch_id ? t("evolution.batchNumber", { id: row.batch_id }) : t("evolution.waitingBatch")}
                    {" · "}{t(`evolution.observation.${row.state}`)}
                    {row.signals.map((signal) => ` · ${t(`evolution.observation.${signal}`)}`)}
                    {row.state === "observed" && <Button type="link" onClick={() => { setPreviousTask(false); setAdding(row.turn_id); }}>
                      {t("evolution.makeTraceCase")}</Button>}
                    {row.state === "observed" && row.signals.includes("user_correction") && (
                      <Button type="link" onClick={() => { setPreviousTask(true); setAdding(row.turn_id); }}>
                        {t("evolution.makeCorrectedCase")}</Button>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}
          <Flex gap={8} wrap align="center">
            <Select
              aria-label={t("evolution.candidate")}
              placeholder={t("evolution.candidate")}
              style={{ minWidth: 220 }}
              value={candidate}
              onChange={v => { setCandidate(v); if (v === "combination") { setSuggestion(undefined); setTargetCase(undefined); } }}
              options={[{ value: "baseline", label: t("evolution.baselineSelection") },
                ...(eligible.length >= 2 ? [{value:"combination", label:t("evolution.combination")}] : []), ...choices.candidates.map((c) => ({
                value: `${c.kind}:${c.candidate_id}`,
                label: `#${c.candidate_id} · ${c.name}`,
              }))]}
            />
            {proposed && <span>{t("evolution.newSkill.heldout")}</span>}
            {candidate === "combination" && <Select mode="multiple" maxCount={2} aria-label={t("evolution.chooseComponents")}
              placeholder={t("evolution.chooseComponents")} value={sourceIds} onChange={setSources} style={{minWidth: 260}}
              options={eligible.map(e => ({ value: e.experiment_id, label: t("evolution.sourceExperiment", {
                experiment: e.experiment_id, candidate: e.candidate_id, type: t(`evolution.kind.${e.candidate_type}`),
              }) }))} />}
            <Select
              mode="multiple"
              aria-label={t("evolution.cases")}
              placeholder={t("evolution.cases")}
              style={{ minWidth: 260 }}
              value={caseIds}
              onChange={ids => { setCases(ids); setTargets(targets.filter(id => ids.includes(id))); }}
              options={choices.cases.filter(c => !discoveryRun || c.expected_skill_names != null).map((c) => ({
                value: c.case_id,
                label: `${c.family} · ${c.query}`,
              }))}
            />
            <Button onClick={() => setAdding(true)}>
              {t("evolution.newCase")}
            </Button>
          </Flex>
          {candidate && candidate !== "baseline" && <>
            <Checkbox checked={screen} onChange={e => setScreen(e.target.checked)}>{t("evolution.screen.enable")}</Checkbox>
            {screen && <Flex gap={8} wrap>
              <Select mode="multiple" aria-label={t("evolution.screen.targets")} placeholder={t("evolution.screen.targets")}
                value={targets} onChange={setTargets} style={{ minWidth: 240 }}
                options={choices.cases.filter(c => caseIds.includes(c.case_id) && !fixedDigests.has(c.digest ?? ""))
                  .map(c => ({value:c.case_id, label:c.query}))} />
              <Select value={metric} onChange={setMetric} aria-label={t("evolution.screen.metric")}
                options={(["tasks_fixed", "input_token_reduction_pct"] as const).map(value => ({
                  value, label:t(`evolution.screen.${value}`),
                }))} />
              <label>{t("evolution.screen.minimum")} <InputNumber min={1} max={100} precision={0} value={minimum}
                aria-label={t("evolution.screen.minimum")} onChange={setMinimum} /></label>
              <Typography.Text>{t("evolution.screen.protection")}</Typography.Text>
            </Flex>}
          </>}
          <Flex gap={8} wrap>
            {suggestion && (
              <Select
                aria-label={t("evolution.suggestionTarget")}
                placeholder={t("evolution.suggestionTarget")}
                style={{ minWidth: 220 }}
                value={caseIds.includes(targetCase ?? 0) ? targetCase : undefined}
                onChange={setTargetCase}
                options={choices.cases.filter((c) => caseIds.includes(c.case_id)).map((c) => ({
                  value: c.case_id, label: c.family,
                }))}
              />
            )}
            <Select
              aria-label={t("evolution.evaluator")}
              placeholder={t("evolution.evaluator")}
              style={{ minWidth: 180 }}
              value={evaluatorId}
              onChange={setEvaluator}
              options={(rules.data || [])
                .filter((r) => r.status === "PUBLISHED")
                .map((r) => ({ value: r.evaluator_id, label: r.name }))}
            />
            {evaluatorId && needsJudge && (
              <Select
                aria-label={t("agentEvaluation.judgeModelLabel")}
                style={{ minWidth: 160 }}
                placeholder={t("agentEvaluation.judgeModelLabel")}
                value={judge}
                onChange={setJudge}
                options={availableLlmModels.map((m) => ({
                  value: m.id,
                  label: m.displayName || m.name,
                }))}
              />
            )}
            <Button
              type="primary"
              disabled={
                !candidate || (!!proposed && scopeLabels.size !== 2) ||
                (candidate !== "baseline" && screen && (!targets.length || !minimum ||
                  (metric === "tasks_fixed" && minimum > targets.length) ||
                  targets.some(id => !caseIds.includes(id) || fixedDigests.has(choices.cases.find(c => c.case_id === id)?.digest ?? "")))) ||
                (candidate === "combination" && (sourceIds.length !== 2 || !!suggestion || !sourceIds.every(id => eligible.some(e => e.experiment_id === id)))) ||
                (candidate === "baseline" && !!suggestion) ||
                (discoveryRun && caseIds.some(id => {
                  const c = choices.cases.find(task => task.case_id === id);
                  return c?.expected_skill_names == null;
                })) ||
                caseIds.length < (suggestion ? 2 : 1) ||
                (!!suggestion && !caseIds.includes(targetCase ?? 0)) ||
                !evaluatorId ||
                (needsJudge && !judge)
              }
              loading={start.isPending}
              onClick={() => start.mutate()}
            >
              {t("evolution.compare")}
            </Button>
          </Flex>
          <Select
            aria-label={t("evolution.history")}
            placeholder={t("evolution.history")}
            style={{ maxWidth: 350 }}
            value={selected}
            onChange={setSelected}
            options={choices.experiments.map((e) => ({
              value: e.experiment_id,
              label: `#${e.experiment_id} · ${new Date(e.create_time).toLocaleString()}`,
            }))}
          />
        </>
      )}
      {report.data && (
        <>
          <Flex gap={12} align="center">
            <Typography.Text>
              {t(baselineReport ? "evolution.baselineCoverage" : "evolution.coverage", {
                valid: baselineReport ? report.data.valid_baselines : report.data.valid_pairs,
                total: baselineReport ? report.data.total_tasks : report.data.total_pairs,
              })}
            </Typography.Text>
            {report.data.valid_triplets !== undefined && <Typography.Text>{t("evolution.skillCoverage", {
              valid: report.data.valid_triplets, total: report.data.total_pairs, read: report.data.verified_guide_pairs,
            })}</Typography.Text>}
            {report.data.components && <Typography.Text>{t("evolution.quartets", {
              valid: report.data.valid_quartets, total: report.data.total_tasks,
              a: report.data.components[0].experiment_id, b: report.data.components[1].experiment_id,
            })}</Typography.Text>}
            {report.data.fixed_regression && <Typography.Text>{t("evolution.fixedCoverage", {
              total: report.data.fixed_regression.case_ids.length,
              failed: report.data.fixed_regression.failed.join(", ") || "—",
              incomplete: report.data.fixed_regression.incomplete.join(", ") || "—",
            })}</Typography.Text>}
            {report.data.screening && <div>
              <strong>{t(`evolution.screen.${report.data.screening.status}`)}</strong>
              <p>{t(`evolution.screen.${report.data.screening.criteria.metric}`)} · {t("evolution.screen.minimum")} {report.data.screening.criteria.minimum}
                {" · "}{t("evolution.screen.observed")} {report.data.screening.gain?.toLocaleString(undefined, {maximumFractionDigits: 2}) ?? "—"}</p>
              {Object.entries({...report.data.screening.failures, ...report.data.screening.missing}).map(([reason, ids]) =>
                <p key={reason}>{t(`evolution.screen.${reason}`)}{ids.length > 0 && ` (#${ids.join(", #")})`}</p>)}
              {report.data.screening.status === "eligible" && <Button loading={nomination.isPending}
                onClick={() => nomination.mutate(report.data!.experiment_id)}>{t("evolution.confirmation.submit")}</Button>}
              {nomination.data?.experiment_id === report.data.experiment_id && <p>{t("evolution.confirmation.receipt", {
                id: nomination.data.experiment_id,
              })} <Typography.Text copyable>{nomination.data.candidate_digest}</Typography.Text></p>}
              {nomination.variables === report.data.experiment_id && nomination.error instanceof Error &&
                <Alert type="error" message={nomination.error.message} />}
              {report.data.screening.status === "eligible" && <div>
                <Button type="link" loading={confirmations.isFetching} onClick={() => void confirmations.refetch()}>
                  {t("evolution.confirmation.refresh")}
                </Button>
                {confirmations.data?.map(({lock_id, summary}) => <p key={lock_id}>
                  #{lock_id} · {t(`evolution.confirmation.${summary?.decision ?? "pending"}`)}
                  {summary && <> · {t("evolution.confirmation.pairs", {valid: summary.valid_pairs,
                    total: summary.total_pairs, regressed: summary.regressed})}</>}
                  {summary?.decision === "passed" && <> · <a href={`/${i18n.language.startsWith("zh") ? "zh" : "en"}/evaluation/releases/${lock_id}`}>
                    {t("evolution.release.open")}
                  </a></>}
                </p>)}
              </div>}
            </div>}
            {active && (
              <Button
                onClick={() => cancel.mutate()}
                loading={cancel.isPending}
              >
                {t("evolution.cancel")}
              </Button>
            )}
          </Flex>
          {development && report.data.status === "finished" && !baselineReport && (
            <ExampleCandidates key={report.data.experiment_id} report={development} cases={choices?.cases || []}
              onGenerated={(id) => {
                setCandidate(`prompt:${id}`);
                setCases([]);
                setSuggestion(undefined);
                void workspace.refetch();
              }}
            />
          )}
          {development && report.data.status === "finished" && choices && Object.values(development.pairs).some(p => p.base.result?.selection) &&
            <DiscoveryFeedback key={report.data.experiment_id} report={development} workspace={choices} />}
          {development && report.data.status === "finished" && choices && <LocalEditFeedback key={report.data.experiment_id}
            report={development} workspace={choices} agent={agent} version={version} viewer={viewer} />}
          {development && report.data.status === "finished" && baselineReport && choices && <NewSkillBriefForm key={report.data.experiment_id} report={development} workspace={choices}/>}
          {development && report.data.status === "finished" && baselineReport && <ToolSetCandidates key={report.data.experiment_id}
            report={development} cases={choices?.cases || []} onSelect={id => {
              setCandidate(`tool_set:${id}`); setCases([]); setSuggestion(undefined); void workspace.refetch();
            }} />}
          <Table
            pagination={false}
            rowKey="id"
            dataSource={Object.entries(report.data.pairs).map(([id, p]) => ({
              id,
              ...p,
            }))}
            columns={[
              {
                title: t("evolution.cases"),
                dataIndex: "id",
                render: (id) => {
                  const task = choices?.cases.find(c => String(c.case_id) === id);
                  return task ? `#${id} · ${task.family}` : `#${id}`;
                },
              },
              ...(report.data.components ? ["base", "only_a", "only_b", "result"] :
                baselineReport ? ["base"] : report.data.valid_triplets === undefined ? ["base", "result"] : ["no_skill", "base", "result"]).map((key) => ({
                title: t(report.data?.components && key === "result" ? "evolution.combinedAB" : `evolution.${key}`),
                dataIndex: key,
                render: (trial?: Trial) => trial && (
                  <div>
                    <strong>{t(`evolution.state.${trial.status}`)}</strong>
                    {trial.result?.skills?.map(s => <div key={s.candidate_id}>{t("evolution.mountedSkill", {
                      id: s.candidate_id, revision: s.mounted_revision, reads: s.guide_reads,
                    })}</div>)}
                    {trial.result?.evaluator_id && <div>{t("evolution.usedRubric", {
                      id: trial.result.evaluator_id, version: trial.result.evaluator_version,
                    })}</div>}
                    <div className="whitespace-pre-wrap">
                      {trial.result?.answer || trial.result?.error}
                    </div>
                    {trial.result?.turns && <details><summary>{t("evolution.turnDetails")}</summary>
                      <ol>{trial.result.turns.map(turn => <li key={turn.turn}>
                        <div>{turn.query}</div>
                        {!!turn.attachments.length && <div>{turn.attachments.join(", ")}</div>}
                        <div className="whitespace-pre-wrap">{turn.answer}</div>
                        {turn.outcome !== "completed" && <code>{turn.outcome}</code>}
                      </li>)}</ol>
                    </details>}
                    {trial.result && <Typography.Text type="secondary">{t("evolution.stepTokens", {
                      tokens: trial.result.reported_step_input_tokens ?? "—",
                    })}</Typography.Text>}
                    {trial.result?.skill && <div title={trial.result.skill.mounted_revision || undefined}>
                      {t("evolution.guideEvidence", {
                        revision: trial.result.skill.mounted_revision?.slice(0, 10) || t("evolution.unmounted"),
                        reads: trial.result.skill.guide_reads,
                      })}
                    </div>}
                    {trial.result?.tool_use && <div>
                      {t("evolution.toolAndDelivery", { tool: t(`evolution.state.${trial.result.tool_use.status}`),
                        delivery: t(`evolution.state.${trial.result.judgment?.status}`) })}
                      <div>{trial.result.tool_use.sequence?.join(" → ")}</div>
                      {trial.result.tool_use.issues?.map((issue, i) => <div key={i}>
                        {issue.tool} {t(`evolution.issue.${issue.reason}`)} {issue.fields?.join(", ")}
                      </div>)}
                    </div>}
                    {trial.result?.file_state && <div>
                      {t("evolution.fileVerdict", { status:t(`evolution.state.${trial.result.file_state.status}`) })}
                      {(["missing","extra","wrong_content","protected_writes"] as const).map(k =>
                        trial.result!.file_state![k].length > 0 && <div key={k}>
                          {t(`evolution.fileIssue.${k}`)} · {trial.result!.file_state![k].join(", ")}
                        </div>)}
                    </div>}
                    {trial.result?.new_skill_trial && <div>
                      {t(trial.result.new_skill_trial.arm === "base" ? "evolution.newSkill.absent" : "evolution.newSkill.mounted",
                        {name: trial.result.new_skill_trial.name, digest: trial.result.new_skill_trial.digest.slice(0,12)})}
                    </div>}
                    {trial.result?.tool_catalog && <details><summary>{t("evolution.actualToolSet")}</summary>
                      {(["prompt_tools","schema_tools","executable"] as const).map(key => <div key={key}>
                        {t(`evolution.catalog.${key}`)} · {trial.result!.tool_catalog![key].join(", ") || "∅"}
                      </div>)}
                      {trial.result.tool_catalog.model_inputs !== undefined && <>
                        <div>{t("evolution.catalog.modelInputs", { count: trial.result.tool_catalog.model_inputs })}</div>
                        {(["instruction_mentions", "native_definitions"] as const).map(key => <div key={key}>
                          {t(`evolution.catalog.${key}`)} · {trial.result!.tool_catalog![key]?.join(", ") || "∅"}
                        </div>)}
                      </>}
                    </details>}
                    {trial.result?.selection && <div>{t("evolution.skillChoice", {
                      expected: trial.result.selection.expected.join(", ") || "∅",
                      reads: Object.keys(trial.result.selection.reads).join(", ") || "∅",
                    })}</div>}
                  </div>
                ),
              })),
              {
                title: t("evolution.change"),
                dataIndex: "comparison",
                render: (value, row) => <div>{t(`evolution.state.${value}`)}
                  {row.base?.result?.trace_baseline_outcome && <div>
                    {t(`evolution.traceOutcome.${row.base.result.trace_baseline_outcome}`)}
                  </div>}
                  {row.combination && <div>{t(`evolution.effect.${row.combination.effect}`)} · {t("evolution.comparedSingles", {
                    a: t(`evolution.state.${row.combination.combined_vs_a}`), b: t(`evolution.state.${row.combination.combined_vs_b}`),
                  })}</div>}
                  {row.skill_vs_absent && <div>{t("evolution.skillVsAbsent", {
                    old: t(`evolution.state.${row.skill_vs_absent.base}`),
                    next: t(`evolution.state.${row.skill_vs_absent.result}`),
                  })}</div>}
                </div>,
              },
            ]}
          />
        </>
      )}
      {typeof adding === "number" && source.error && <Alert type="error" message={source.error.message}
        closable onClose={() => setAdding(false)} />}
      {typeof adding === "number" && source.isLoading && <Typography.Text>{t("evolution.loadingDraft")}</Typography.Text>}
      {adding && (adding === true || source.data) && (
        <CaseForm
          key={`${adding}-${previousTask}-${preceding}`}
          draft={typeof adding === "number" ? source.data : undefined}
          agent={agent}
          version={version}
          skills={[...new Set([...(choices?.skills || []).map(s => s.name),
            ...(choices?.candidates || []).filter(c => c.kind === "skill_new").map(c => c.name)])].map(name => ({name}))}
          close={() => setAdding(false)}
          saved={(id) => {
            if (typeof adding === "number") {
              setCandidate("baseline");
              setSuggestion(undefined);
              setTargetCase(undefined);
              setCases([id]);
            } else {
              setCases(current => [...new Set([...current, id])]);
            }
            setAdding(false);
            void workspace.refetch();
          }}
        />
      )}
    </Flex>
  );
}

export default function EvolutionExperiments() {
  const { user } = useAuthorizationContext();
  if (!user) return null;
  const viewer = JSON.stringify([user.tenantId, user.id]);
  return <AgentPicker key={viewer} viewer={viewer} />;
}

function AgentPicker({ viewer }: { viewer: string }) {
  const { t } = useTranslation("common");
  const [agent, setAgent] = useState<number>();
  const [version, setVersion] = useState<number>();
  const agents = useQuery({
    queryKey: ["evolution-agents", viewer],
    queryFn: api.agents,
  });
  const versions = useQuery({
    queryKey: ["evolution-versions", viewer, agent],
    queryFn: () => api.versions(agent!),
    enabled: !!agent,
  });
  const error = agents.error || versions.error;
  return (
    <Flex vertical gap={16}>
      <ResourceCandidateGenerator />
      {error instanceof Error && <Alert type="error" message={error.message} />}
      <Flex gap={8}>
        <Select
          showSearch
          optionFilterProp="label"
          aria-label={t("agentEvaluation.agentLabel")}
          value={agent}
          style={{ minWidth: 230 }}
          placeholder={t("agentEvaluation.selectAgent")}
          options={agents.data?.map((a) => ({
            value: a.agent_id,
            label: a.display_name || a.name,
          }))}
          onChange={(id) => {
            setAgent(id);
            setVersion(undefined);
          }}
        />
        <Select
          aria-label={t("agentEvaluation.agentVersionLabel")}
          disabled={!agent}
          value={version}
          style={{ minWidth: 150 }}
          placeholder={t("agentEvaluation.agentVersionLabel")}
          onChange={setVersion}
          options={versions.data
            ?.filter((v) => v.version_no > 0)
            .map((v) => ({
              value: v.version_no,
              label: `V${v.version_no} ${v.version_name || ""}`,
            }))}
        />
      </Flex>
      {agent && version && (
        <Experiments
          key={`${agent}:${version}`}
          agent={agent}
          version={version}
          viewer={viewer}
        />
      )}
    </Flex>
  );
}
