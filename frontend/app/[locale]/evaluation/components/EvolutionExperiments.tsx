// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import { useRef, useState } from "react";
import Link from "next/link";
import {
  Alert,
  Button,
  Card,
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
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useModelList } from "@/hooks/model/useModelList";
import { businessSetKeys, evolutionService as api, type BusinessEvaluationSet, type BusinessSetCase,
  type Trial, type TraceCaseDraft, type ScreeningCriteria, type LocalFeedback } from "@/services/evolutionService";
import { storageService } from "@/services/storageService";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { ResourceCandidateGenerator } from "./DiscoveryFeedback";
import ToolUseRules, { toolExpectation, type ToolRuleFields } from "./ToolUseRules";
import FileStateRules, { fileStateRule, type FileRule } from "./FileStateRules";
import LocalEditFeedback from "./LocalEditFeedback";
import { ToolMaintainerBrief } from "./ToolRepair";
import { ScriptDraftForm } from "./SkillScriptRepair";
import FixedRegressionCases from "./FixedRegressionCases";
import PublicBenchmarkReports from "./PublicBenchmarkReports";
import ReviewBatchResults from "./ReviewBatchResults";
import EvolutionGenerationMethods from "./EvolutionGenerationMethods";
import { EvolutionDirectionGuide, evolutionHref, matchesDirection, readEvolutionDirection, type EvolutionDirection } from "./EvolutionDirections";

function CaseForm({
  agent,
  version,
  skills,
  direction,
  draft,
  groups,
  initialSet,
  close,
  saved,
}: {
  agent: number;
  version: number;
  skills: { name: string }[];
  direction?: EvolutionDirection;
  draft?: TraceCaseDraft;
  groups: BusinessEvaluationSet[];
  initialSet?: number;
  close: () => void;
  saved: (id: number, setId?: number) => void;
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
  const [group, setGroup] = useState<number | "new" | undefined>(initialSet);
  const [groupName, setGroupName] = useState("");
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
        evaluation_set_id: typeof group === "number" ? group : undefined,
        new_evaluation_set_name: group === "new" ? groupName.trim() : undefined,
        attachments,
        expected_skill_names: labelSkill ? expectedSkills : undefined,
        trace: draft && { turn_id: draft.turn_id, draft_digest: draft.draft_digest, purpose,
          inputs_reviewed: true, tools_require_no_reset: stateless, unused_attachment_slots: unused,
          use_previous_task: !!draft.correction_trajectory_id,
          ...(draft.preceding_turns ? { preceding_turns: draft.preceding_turns } : {}) },
      });
    },
    onSuccess: (response) => saved(response.case_id, response.evaluation_set_id),
  });
  return (
    <Modal
      open
      title={t("evolution.newCase")}
      onCancel={close}
      onOk={() => mutation.mutate()}
      confirmLoading={mutation.isPending}
      okButtonProps={{ disabled: (group === "new" && !groupName.trim()) || (!!draft && (!reviewed || draft.attachment_count == null ||
        files.length + unused.length < draft.attachment_count || (draft.tool_count > 0 && !stateless && !verifyFiles))) }}
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
        <Form.Item label={t("evolution.sets.destination")}>
          <Select<number | "new"> allowClear aria-label={t("evolution.sets.destination")}
            placeholder={t("evolution.sets.destinationPlaceholder")} value={group} onChange={setGroup}
            options={[...groups.map((item) => ({ value: item.evaluation_set_id, label: item.name })),
              { value: "new", label: t("evolution.sets.create") }]} />
        </Form.Item>
        {group === "new" && <Form.Item label={t("evolution.sets.name")} required>
          <Input aria-label={t("evolution.sets.name")} value={groupName} maxLength={100}
            onChange={(event) => setGroupName(event.target.value)} />
        </Form.Item>}
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
        {(!direction || direction === "skill" || direction === "combination") && <>
          <Checkbox checked={labelSkill} onChange={e => setLabelSkill(e.target.checked)}>{t("evolution.labelSkill")}</Checkbox>
          {labelSkill && <Form.Item label={t("evolution.acceptableSkills")}>
            <Select mode="multiple" value={expectedSkills} onChange={setExpectedSkills}
              options={skills.map(s => ({ value: s.name, label: s.name }))} />
          </Form.Item>}
        </>}
        {direction === "prompt" || direction === "skill" ? <details>
          <summary>{t("evolution.direction.additionalToolChecks")}</summary>
          <ToolUseRules />
        </details> : <ToolUseRules />}
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

interface ComparisonFocus {
  agent?: number;
  version?: number;
  suggestion?: number;
  candidate?: number;
  experiment?: number;
  evaluationSet?: number;
}

const evolutionSteps = ["cases", "baseline", "generate", "compare", "release"] as const;
type EvolutionStep = typeof evolutionSteps[number];
const directionMethods: Record<Exclude<EvolutionDirection, "combination">, LocalFeedback["method"][]> = {
  prompt: ["P1", "P3"],
  skill: ["S2"],
  tool: ["T1", "T2"],
};
const internalCandidateNames = new Set(["agent.prompt", "agent.tools", "agent.tool_format"]);

function Experiments({
  agent,
  version,
  viewer,
  focus,
  direction,
}: {
  agent: number;
  version: number;
  viewer: string;
  focus?: ComparisonFocus;
  direction?: EvolutionDirection;
}) {
  const { t, i18n } = useTranslation("common");
  const { availableLlmModels } = useModelList();
  const queryClient = useQueryClient();
  const [stage, setStage] = useState<EvolutionStep>();
  const [feedback, setFeedback] = useState<{ id: number; kind: "resource" | "script" }>();
  const [caseIds, setCases] = useState<number[]>([]);
  const [evaluationSet, setEvaluationSet] = useState<number | undefined>(focus?.agent === agent ? focus.evaluationSet : undefined);
  const [loadedSetCases, setLoadedSetCases] = useState<BusinessSetCase[]>([]);
  const [screen, setScreen] = useState(false);
  const [chosenMetric, setMetric] = useState<ScreeningCriteria["metric"]>("tasks_fixed");
  const [turnLimit, setTurnLimit] = useState<number | null>(1000);
  const [elapsedLimit, setElapsedLimit] = useState<number | null>(3600);
  const [modelTokenLimit, setModelTokenLimit] = useState<number | null>(null);
  const [modelDollarLimit, setModelDollarLimit] = useState<number | null>(null);
  const [minimum, setMinimum] = useState<number | null>(1);
  const [targets, setTargets] = useState<number[]>([]);
  const [candidate, setCandidate] = useState<string | undefined>(focus?.candidate ? `skill_step:${focus.candidate}` : undefined);
  const discoveryCandidate = candidate?.startsWith("skill_discovery:");
  const metric = chosenMetric === "skill_choices_fixed" && !discoveryCandidate ? "tasks_fixed" : chosenMetric;
  const metricOptions: ScreeningCriteria["metric"][] = ["tasks_fixed", "input_token_reduction_pct"];
  if (discoveryCandidate) metricOptions.unshift("skill_choices_fixed");
  const [sourceIds, setSources] = useState<number[]>([]);
  const [suggestion, setSuggestion] = useState<number | undefined>(focus?.suggestion);
  const [targetCase, setTargetCase] = useState<number>();
  const [evaluatorId, setEvaluator] = useState<number>();
  const [judge, setJudge] = useState<number>();
  const [selected, setSelected] = useState<number | undefined>(focus?.experiment);
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
  const businessSets = useQuery({
    queryKey: businessSetKeys.list(viewer, agent),
    queryFn: () => api.businessSets(agent),
  });
  const loadBusinessSet = useMutation({
    mutationFn: (setId: number) => api.selectBusinessSet(agent, version, setId),
    onSuccess: (cases) => {
      setLoadedSetCases(cases);
      setCases(cases.map((item) => item.case_id));
      setTargets([]);
      setTargetCase(undefined);
      void workspace.refetch();
    },
  });
  const rules = useQuery({
    queryKey: ["evolution-evaluators", viewer],
    queryFn: api.evaluators,
  });
  const needsJudge =
    rules.data?.find((item) => item.evaluator_id === evaluatorId)
      ?.evaluator_type !== "code";
  const report = useQuery({
    queryKey: ["experiment-report", viewer, selected, agent, version],
    queryFn: async () => {
      const result = await api.report(selected!);
      if (selected === focus?.experiment && (result.agent_id !== agent || result.version_no !== version)) {
        throw new Error(t("evolution.receipt.reportScope"));
      }
      return result;
    },
    enabled: !!selected && (selected !== focus?.experiment || workspace.isSuccess),
    retry: false,
    refetchInterval: (query) =>
      ["pending", "running"].includes(query.state.data?.status || "")
        ? 2000
        : false,
  });
  const selectedExperiment = workspace.data?.experiments.find(item => item.experiment_id === selected);
  const baselineReport = selectedExperiment?.candidate_type
    ? selectedExperiment.candidate_type === "baseline"
    : report.data?.total_pairs === 0;
  const step = stage ?? (focus?.candidate ? "compare" : focus?.experiment
    ? baselineReport ? "baseline" : "compare"
    : focus?.suggestion ? "generate" : direction === "combination" ? "compare" : "cases");
  const runCandidate = step === "baseline" ? "baseline" : candidate;
  const showRun = step === "baseline" || step === "compare";
  const reportVisible = report.data && (step === "baseline" ? baselineReport
    : (step === "compare" || step === "release") && !baselineReport);
  const publishedRules = (rules.data || []).filter((rule) => rule.status === "PUBLISHED");
  const modelOptions = availableLlmModels.map((model) => ({ value: model.id, label: model.displayName || model.name }));
  const start = useMutation({
    mutationFn: () => {
      const [kind, id] = runCandidate!.split(":");
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
        suggestion_id: kind !== "baseline" ? suggestion : undefined,
        suggestion_target_case_id: kind !== "baseline" && suggestion ? targetCase : undefined,
        case_ids: caseIds,
        screening: screen && kind !== "baseline" ? { metric, minimum: minimum!, target_case_ids: targets } : undefined,
        budget: {
          max_replay_turns: turnLimit!,
          max_elapsed_seconds: elapsedLimit!,
          ...(workspace.data?.model_budget_available && modelTokenLimit !== null ? { max_model_tokens: modelTokenLimit } : {}),
          ...(workspace.data?.model_budget_available && modelDollarLimit !== null
            ? { max_model_micros: Math.round(modelDollarLimit * 1_000_000) } : {}),
        },
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
  const retry = useMutation({ mutationFn: (id: number) => api.retry(id), onSuccess: () => void report.refetch() });
  const nomination = useMutation({ mutationFn: (id: number) => api.nominate(id) });
  const confirmations = useQuery({
    queryKey: ["confirmation-results", viewer, agent, version, selected],
    queryFn: () => api.confirmationResults(selected!),
    enabled: step === "release" && !!selected && report.data?.screening?.status === "eligible",
    retry: false,
    refetchInterval: query => query.state.data?.some(row => !row.summary) ? 10000 : false,
  });
  const choices = workspace.data && {
    ...workspace.data,
    cases: [...new Map([...workspace.data.cases, ...loadedSetCases].map((item) => [item.case_id, item])).values()],
  };
  const candidates = choices?.candidates.filter(c => matchesDirection(direction, c.kind, c.optimization_methods)) ?? [];
  const history = choices?.experiments.filter(e => !e.candidate_type || step === "generate" ||
    (step === "baseline" ? e.candidate_type === "baseline" : e.candidate_type !== "baseline"))
    .filter(e => !e.candidate_type || e.candidate_type === "baseline" ||
      matchesDirection(direction, e.candidate_type, e.optimization_methods)) ?? [];
  const eligible = choices?.experiments.filter(e => e.eligible_component && e.candidate_type && e.candidate_id) || [];
  const showCombination = (!direction || direction === "combination") && eligible.length >= 2;
  const steps = direction === "combination" ? evolutionSteps.filter(item => item !== "generate") : evolutionSteps;
  const showSkill = !direction || direction === "skill";
  const fixedIds = new Set(report.data?.fixed_regression?.case_ids ?? []);
  const fixedDigests = new Set(choices?.fixed_regression?.map(c => c.digest));
  choices?.cases.forEach(c => {
    if ((c.digest && fixedDigests.has(c.digest)) || choices.fixed_regression?.some(member =>
      member.source_version === version && member.source_case_id === c.case_id)) fixedIds.add(c.case_id);
  });
  const development = report.data && { ...report.data, pairs: Object.fromEntries(
    Object.entries(report.data.pairs).filter(([id]) => !fixedIds.has(Number(id)))) };
  const proposed = choices?.candidates.find(c => c.kind === "skill_new" && candidate === `skill_new:${c.candidate_id}`);
  const discoveryRun = discoveryCandidate || !!proposed || (candidate === "combination" &&
    eligible.some(e => sourceIds.includes(e.experiment_id) && e.candidate_type === "skill_discovery"));
  const scopeLabels = new Set(choices?.cases.filter(c => caseIds.includes(c.case_id) &&
    !fixedDigests.has(c.digest ?? "") && c.expected_skill_names != null).map(c => c.expected_skill_names!.includes(proposed?.name ?? "")));
  const active = ["pending", "running"].includes(report.data?.status || "");
  const selectCandidate = (kind: string, id: number) => {
    setCandidate(`${kind}:${id}`);
    setCases([]);
    setTargets([]);
    if (kind !== "skill_step") setSuggestion(undefined);
    setTargetCase(undefined);
    setStage("compare");
    void workspace.refetch();
  };
  const advanceToBaseline = () => setStage("baseline");
  const nextFromCases = direction === "combination" ? "compare" : "baseline";
  const receiveResourceFeedback = (id: number) => setFeedback({ id, kind: "resource" });
  const receiveLocalEdit = (id: number, suggestionId?: number) => {
    setSuggestion(suggestionId);
    receiveResourceFeedback(id);
  };
  const goToDraft = (turn: number, previous: boolean) => {
    setPreceding(0);
    setPreviousTask(previous);
    setAdding(turn);
  };
  const error =
    workspace.error ||
    businessSets.error ||
    loadBusinessSet.error ||
    rules.error ||
    start.error ||
    report.error ||
    cancel.error || (retry.variables === selected ? retry.error : null) || confirmations.error;
  return (
    <Flex vertical gap={14}>
      <nav aria-label={t("evolution.workflow.navigation")}>
        <Flex gap={8} wrap>
          {steps.map((item) => <Button key={item} type={item === step ? "primary" : "default"}
            aria-current={item === step ? "step" : undefined} onClick={() => setStage(item)}>
            {t(`evolution.workflow.${item}`)}
          </Button>)}
        </Flex>
      </nav>
      <Typography.Text type="secondary">{t(`evolution.workflow.${step}Help`)}</Typography.Text>
      {direction && direction !== "combination" && ["cases", "generate"].includes(step) && (
        <Typography.Text>{t(`evolution.direction.${direction}.${step}`)}</Typography.Text>
      )}
      {error instanceof Error && (
        <Alert type="error" showIcon message={error.message} />
      )}
      {choices && (
        <>
          {showSkill && (step === "generate" || step === "compare" && candidate !== "combination") && !!choices.suggestions?.length && (
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
          {step === "cases" && <>
          <Link href={`?tab=sets&agent_id=${agent}`}>{t("evolution.sets.catalog")}</Link>
          <FixedRegressionCases agent={agent} version={version} workspace={choices} refresh={workspace.refetch}
            rubrics={publishedRules} models={modelOptions} suggestedEvaluator={evaluatorId} suggestedJudge={judge}
            onNewCase={() => setAdding(true)} />
          {!!choices.review_batches?.length && <ReviewBatchResults batches={choices.review_batches}
            refreshing={workspace.isFetching} refresh={() => void workspace.refetch()}
            onDraft={goToDraft} />}
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
                    {row.diagnosis && row.diagnosis.reason !== "no_signal" && <div>
                      {t(`evolution.diagnosis.${row.diagnosis.status}`)} · {t(`evolution.diagnosis.${row.diagnosis.reason}`)}
                      {row.diagnosis.missing?.map(item => ` · ${t(`evolution.diagnosis.${item}`)}`)}
                    </div>}
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
          <div><Button type="primary" onClick={() => setStage(nextFromCases)}>{t(nextFromCases === "baseline"
            ? "evolution.workflow.toBaseline" : "evolution.direction.toComparison")}</Button></div>
          </>}
          {showRun && <>
          {step === "compare" && !candidates.length && !showCombination && (
            <Alert showIcon type="info" message={t(direction === "combination" ? "evolution.direction.needsComponents" : "evolution.workflow.noCandidate")}
              action={direction !== "combination" && <Button size="small" onClick={() => setStage("generate")}>{t("evolution.workflow.toGenerate")}</Button>} />
          )}
          <Flex gap={8} wrap align="center">
            {step === "compare" && <Select
              aria-label={t("evolution.candidate")}
              placeholder={t("evolution.candidate")}
              style={{ minWidth: 220 }}
              value={candidate}
              showSearch={{ optionFilterProp: "label" }}
              onChange={v => { setCandidate(v); if (v === "combination") { setSuggestion(undefined); setTargetCase(undefined); } }}
              options={[
                ...(showCombination ? [{value:"combination", label:t("evolution.combination")}] : []), ...candidates.map((c) => ({
                value: `${c.kind}:${c.candidate_id}`,
                label: `#${c.candidate_id} · ${internalCandidateNames.has(c.name)
                  ? t(direction && c.kind === "prompt" ? `evolution.direction.${direction}.edit` : `evolution.kind.${c.kind}`)
                  : c.name}`,
              }))]}
            />}
            {step === "compare" && proposed && <span>{t("evolution.newSkill.heldout")}</span>}
            {step === "compare" && candidate === "combination" && <Select mode="multiple" maxCount={2} aria-label={t("evolution.chooseComponents")}
              placeholder={t("evolution.chooseComponents")} value={sourceIds} onChange={setSources} style={{minWidth: 260}}
              options={eligible.map(e => ({ value: e.experiment_id, label: t("evolution.sourceExperiment", {
                experiment: e.experiment_id, candidate: e.candidate_id, type: t(`evolution.kind.${e.candidate_type}`),
              }) }))} />}
            {!!businessSets.data?.length && <>
              <Select<number> allowClear aria-label={t("evolution.sets.select")}
                placeholder={t("evolution.sets.select")} style={{ minWidth: 220 }}
                disabled={loadBusinessSet.isPending} value={evaluationSet} onChange={setEvaluationSet}
                options={businessSets.data.map((group) => ({ value: group.evaluation_set_id,
                  label: `${group.name} (${group.case_count})`, disabled: !group.case_count }))} />
              <Button disabled={!evaluationSet} loading={loadBusinessSet.isPending}
                onClick={() => { if (evaluationSet) loadBusinessSet.mutate(evaluationSet); }}>
                {t("evolution.sets.useCases")}
              </Button>
            </>}
            <Select
              mode="multiple"
              showSearch={{ optionFilterProp: "label" }}
              aria-label={t("evolution.cases")}
              placeholder={t("evolution.cases")}
              style={{ minWidth: 260 }}
              value={caseIds}
              onChange={ids => { setCases(ids); setTargets(targets.filter(id => ids.includes(id))); }}
              options={choices.cases.filter(c => step === "baseline" || !discoveryRun || c.expected_skill_names != null).map((c) => ({
                value: c.case_id,
                label: `${c.family} · ${c.query}`,
              }))}
            />
          </Flex>
          <details>
          <summary>{t("evolution.workflow.advancedRun")}</summary>
          <Flex gap={12} wrap>
            <label>{t("evolution.budget.turns")} <InputNumber value={turnLimit} onChange={setTurnLimit}
              aria-label={t("evolution.budget.turns")} min={1} max={10000} precision={0} /></label>
            <label>{t("evolution.budget.elapsed")} <InputNumber value={elapsedLimit} onChange={setElapsedLimit}
              aria-label={t("evolution.budget.elapsed")} min={1} max={604800} precision={0} /></label>
            {choices.model_budget_available && <>
              <label>{t("evolution.budget.modelTokens")} <InputNumber value={modelTokenLimit}
                onChange={setModelTokenLimit} aria-label={t("evolution.budget.modelTokens")} min={1} max={10 ** 12} precision={0} /></label>
              <label>{t("evolution.budget.modelCost")} <InputNumber value={modelDollarLimit}
                onChange={setModelDollarLimit} aria-label={t("evolution.budget.modelCost")} min={0} max={10 ** 9}
                step={0.01} precision={6} /></label>
            </>}
          </Flex>
          </details>
          {step === "compare" && candidate && <>
            <Checkbox checked={screen} onChange={e => setScreen(e.target.checked)}>{t("evolution.screen.enable")}</Checkbox>
            {screen && <Flex gap={8} wrap>
              <Select mode="multiple" showSearch={{ optionFilterProp: "label" }}
                aria-label={t("evolution.screen.targets")} placeholder={t("evolution.screen.targets")}
                value={targets} onChange={setTargets} style={{ minWidth: 240 }}
                options={choices.cases.filter(c => caseIds.includes(c.case_id) && !fixedDigests.has(c.digest ?? ""))
                  .map(c => ({value:c.case_id, label:c.query}))} />
              <Select value={metric} onChange={setMetric} aria-label={t("evolution.screen.metric")}
                options={metricOptions.map(value => ({
                  value, label:t(`evolution.screen.${value}`),
                }))} />
              <label>{t("evolution.screen.minimum")} <InputNumber min={1} max={100} precision={0} value={minimum}
                aria-label={t("evolution.screen.minimum")} onChange={setMinimum} /></label>
              <Typography.Text>{t("evolution.screen.protection")}</Typography.Text>
            </Flex>}
          </>}
          <Flex gap={8} wrap>
            {step === "compare" && suggestion && (
              <Select
                aria-label={t("evolution.suggestionTarget")}
                placeholder={t("evolution.suggestionTarget")}
                style={{ minWidth: 220 }}
                value={caseIds.includes(targetCase ?? 0) ? targetCase : undefined}
                showSearch={{ optionFilterProp: "label" }}
              onChange={(id) => {
                setTargetCase(id);
                const task = choices.cases.find(c => c.case_id === id);
                if ((!targets.length || (targets.length === 1 && targets[0] === targetCase))
                  && !fixedDigests.has(task?.digest ?? "")) setTargets([id]);
              }}
                options={choices.cases.filter((c) => caseIds.includes(c.case_id)).map((c) => ({
                  value: c.case_id, label: c.query,
                }))}
              />
            )}
            <Select
              aria-label={t("evolution.evaluator")}
              placeholder={t("evolution.evaluator")}
              style={{ minWidth: 180 }}
              value={evaluatorId}
              onChange={setEvaluator}
              options={publishedRules
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
                !turnLimit || !elapsedLimit || !runCandidate || (step === "compare" && !!proposed && scopeLabels.size !== 2) ||
                (step === "compare" && screen && (!targets.length || !minimum ||
                  (metric !== "input_token_reduction_pct" && minimum > targets.length) ||
                  targets.some(id => !caseIds.includes(id) || fixedDigests.has(choices.cases.find(c => c.case_id === id)?.digest ?? "")))) ||
                (step === "compare" && candidate === "combination" &&
                  (sourceIds.length !== 2 || !!suggestion || !sourceIds.every(id => eligible.some(e => e.experiment_id === id)))) ||
                (step === "compare" && discoveryRun && caseIds.some(id => {
                  const c = choices.cases.find(task => task.case_id === id);
                  return c?.expected_skill_names == null;
                })) ||
                loadBusinessSet.isPending || caseIds.length < (step === "compare" && suggestion ? 2 : 1) ||
                (step === "compare" && !!suggestion && !caseIds.includes(targetCase ?? 0)) ||
                !evaluatorId ||
                (needsJudge && !judge)
              }
              loading={start.isPending}
              onClick={() => start.mutate()}
            >
              {t(step === "baseline" ? "evolution.workflow.startBaseline" : "evolution.compare")}
            </Button>
          </Flex>
          {step === "compare" && !!choices.fixed_regression?.length && (
            <Typography.Text type="secondary">{t("evolution.workflow.fixedIncluded", { count: choices.fixed_regression.length })}</Typography.Text>
          )}
          </>}
          {step !== "cases" && <Flex gap={8} wrap align="center">
          <Select
            aria-label={t("evolution.history")}
            placeholder={t("evolution.history")}
            style={{ maxWidth: 350 }}
            value={history.some(item => item.experiment_id === selected) ? selected : undefined}
            onChange={(id) => { setSelected(id); setFeedback(undefined); }}
            options={history.map((e) => ({
              value: e.experiment_id,
              label: `#${e.experiment_id} · ${t(e.candidate_type === "baseline" ? "evolution.workflow.baseline" : "evolution.workflow.compare")} · ${new Date(e.create_time).toLocaleString()}`,
            }))}
          />
          {step === "generate" && !report.data && (
            <Button onClick={advanceToBaseline}>{t("evolution.workflow.toBaseline")}</Button>
          )}
          </Flex>}
        </>
      )}
      {step === "generate" && direction !== "combination" && choices && <>
        {development && report.data?.status === "finished" ? (
          <Flex vertical gap={12}>
            <div><LocalEditFeedback key={`local-${development.experiment_id}`} report={development}
              workspace={choices} agent={agent} version={version} viewer={viewer} suggestedId={suggestion}
              onFeedback={receiveLocalEdit} methods={direction ? directionMethods[direction] : undefined}
              label={direction ? t(`evolution.direction.${direction}.edit`) : undefined} /></div>
            <EvolutionGenerationMethods key={development.experiment_id} direction={direction} baseline={!!baselineReport}
              report={development} workspace={choices} scope={{ agent, version, viewer }} onResource={receiveResourceFeedback}
              onScript={id => setFeedback({ id, kind: "script" })} onCandidate={selectCandidate} />
          </Flex>
        ) : (
          <Alert type="info" showIcon message={t("evolution.workflow.needsEvidence")} />
        )}
        {feedback && <Card size="small" title={t(feedback.kind === "script"
          ? "evolution.workflow.scriptTitle" : "evolution.workflow.generateTitle")}
          extra={<Typography.Text type="secondary" copyable={{
            text: `${window.location.origin}${window.location.pathname}?tab=evolution&feedback_id=${feedback.id}&feedback_kind=${feedback.kind}`,
          }}>{t("evolution.workflow.shareHandoff")}</Typography.Text>}>
          {feedback.kind === "script" ? <ScriptDraftForm key={feedback.id} feedbackId={feedback.id}
            onSelect={(id) => selectCandidate("skill_script", id)} />
            : <ResourceCandidateGenerator key={feedback.id} feedbackId={feedback.id} onSelect={selectCandidate} />}
        </Card>}
      </>}
      {step === "release" && !reportVisible && (
        <Alert showIcon type="info" message={t("evolution.workflow.needsComparison")} />
      )}
      {report.data && reportVisible && (
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
            {report.data.budget && <Typography.Text>{t("evolution.budget.report", {
              planned: report.data.budget.planned_replay_turns, limit: report.data.budget.max_replay_turns,
              deadline: new Date(report.data.budget.deadline).toLocaleString(), expired: report.data.budget.expired_trials,
            })}</Typography.Text>}
            {report.data.model_budget && <Typography.Text>{t("evolution.budget.modelUsage", {
              tokens: report.data.model_budget.reported_input_tokens + report.data.model_budget.reported_output_tokens,
              tokenLimit: report.data.model_budget.max_model_tokens,
              dollars: (report.data.model_budget.reported_micros / 1_000_000).toFixed(6),
              dollarLimit: (report.data.model_budget.max_model_micros / 1_000_000).toFixed(6),
              pending: report.data.model_budget.calls - report.data.model_budget.reported_calls,
              reservedTokens: report.data.model_budget.unsettled_tokens,
              reservedCost: (report.data.model_budget.unsettled_micros / 1_000_000).toFixed(6),
            })}</Typography.Text>}
            {report.data.model_budget?.stopped_reason && <Alert type="warning" showIcon
              title={t("evolution.budget.modelStopped")} />}
            {report.data.fixed_regression && <Typography.Text>{t("evolution.fixedCoverage", {
              total: report.data.fixed_regression.case_ids.length,
              failed: report.data.fixed_regression.failed.join(", ") || "—",
              incomplete: report.data.fixed_regression.incomplete.join(", ") || "—",
            })}</Typography.Text>}
            {step === "release" && report.data.screening && <div>
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
                  {summary?.model_usage && <> · {t("evolution.confirmation.modelUsage", {
                    tokens: summary.model_usage.input_tokens + summary.model_usage.output_tokens,
                    dollars: (summary.model_usage.cost_micros / 1_000_000).toFixed(6),
                    reservedTokens: summary.model_usage.unsettled_tokens,
                    reservedCost: (summary.model_usage.unsettled_micros / 1_000_000).toFixed(6),
                  })}</>}
                  {summary?.missing?.includes("confirmation_model_budget_exceeded") && <>
                    {" · "}{t("evolution.confirmation.modelStopped")}
                  </>}
                  {summary?.missing?.includes("confirmation_arm_interrupted") && <>
                    {" · "}{t("evolution.confirmation.interrupted")}
                  </>}
                  {summary?.decision === "passed" && <> · <a href={`/${i18n.language.startsWith("zh") ? "zh" : "en"}/evaluation/releases/${lock_id}`}>
                    {t("evolution.release.open")}
                  </a></>}
                </p>)}
              </div>}
            </div>}
            {active && step !== "release" && (
              <Button
                onClick={() => cancel.mutate()}
                loading={cancel.isPending}
              >
                {t("evolution.cancel")}
              </Button>
            )}
            {step !== "release" && report.data.can_retry && <Button loading={retry.isPending}
              onClick={() => retry.mutate(report.data.experiment_id)}>{t("evolution.retryInconclusive")}</Button>}
          </Flex>
          {step === "baseline" && report.data.status === "finished" && (
            <div><Button type="primary" onClick={() => setStage(direction === "combination" ? "compare" : "generate")}>
              {t(direction === "combination" ? "evolution.direction.toComparison" : "evolution.workflow.toGenerate")}
            </Button></div>
          )}
          {step === "compare" && report.data.status === "finished" && (
            <div><Button onClick={() => setStage("release")}>{t("evolution.workflow.toRelease")}</Button></div>
          )}
          {step === "release" && !report.data.screening && (
            <Alert showIcon type="info" message={t("evolution.workflow.needsScreening")} />
          )}
          {step === "compare" && report.data.status === "finished" && (
            <PublicBenchmarkReports
              key={report.data.experiment_id}
              experiment={report.data.experiment_id}
              viewer={viewer}
            />
          )}
          {step !== "release" && <Table
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
                  const label = task ? `#${id} · ${task.family}` : `#${id}`;
                  return report.data?.script_source_cases?.includes(Number(id)) ? `${label} · ${t("evolution.scriptRecheck")}` : label;
                },
              },
              ...(report.data.components ? ["base", "only_a", "only_b", "result"] :
                baselineReport ? ["base"] : report.data.valid_triplets === undefined ? ["base", "result"] : ["no_skill", "base", "result"]).map((key) => ({
                title: t(report.data?.components && key === "result" ? "evolution.combinedAB" : `evolution.${key}`),
                dataIndex: key,
                render: (trial?: Trial) => trial && (
                  <div>
                    <strong>{t(`evolution.state.${trial.status}`)}</strong>
                    {trial.result?.previous_attempt && <details>
                      <summary>{t("evolution.previousAttempt", {
                        status: t(`evolution.state.${trial.result.previous_attempt.status}`),
                      })}</summary>
                      <div>{trial.result.previous_attempt.result?.error || trial.result.previous_attempt.result?.judgment?.reason
                        || trial.result.previous_attempt.result?.tool_use?.reason}</div>
                      <code>{trial.result.previous_attempt.receipt_id}</code>
                    </details>}
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
                      {trial.result.tool_use.reason === "unverified_script_files" && <div>{t("evolution.scriptFilesMissing")}</div>}
                      {trial.result.tool_use.reason === "unverified_skill_process" && <div>{t("evolution.scriptMissing")}</div>}
                      {(trial.result.tool_use.reason === "unverified_mcp_reply" || trial.result.tool_use.reason === "unverified_mcp_fixture") &&
                        <div>{t(`evolution.issue.${trial.result.tool_use.reason}`)}</div>}
                      {trial.result.tool_use.mcp_evidence?.map(e => <div key={e.call}>{t("evolution.mcpOutcome", {
                        tool: e.tool, input: t(e.input_matches ? "evolution.match" : "evolution.mismatch"),
                        reply: t(e.reply_matches ? "evolution.match" : "evolution.mismatch"),
                        state: t(e.state_matches == null ? "evolution.notChecked" : e.state_matches ? "evolution.match" : "evolution.mismatch"),
                      })}</div>)}
                      {trial.result.tool_use.script_evidence?.map(s => <div key={s.call}>{t("evolution.scriptOutcome", {
                        call: s.call, code: s.exit_code, input: t(s.input_matches ? "evolution.match" : "evolution.mismatch"),
                        output: t(s.stdout_matches == null ? "evolution.notChecked" : s.stdout_matches ? "evolution.match" : "evolution.mismatch"),
                        files: t(s.files_match == null ? "evolution.notChecked" : s.files_match ? "evolution.match" : "evolution.mismatch"),
                      })}</div>)}
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
          />}
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
          direction={direction}
          groups={businessSets.data ?? []}
          initialSet={evaluationSet}
          skills={[...new Set([...(choices?.skills || []).map(s => s.name),
            ...(choices?.released_guides || []).map(s => s.name),
            ...(choices?.candidates || []).filter(c => c.kind === "skill_new").map(c => c.name)])].map(name => ({name}))}
          close={() => setAdding(false)}
          saved={(id, setId) => {
            if (setId) {
              setEvaluationSet(setId);
              void queryClient.invalidateQueries({ queryKey: businessSetKeys.list(viewer, agent) });
              void queryClient.invalidateQueries({ queryKey: businessSetKeys.detail(viewer, agent, setId) });
            }
            void queryClient.invalidateQueries({ queryKey: businessSetKeys.choices(viewer, agent) });
            if (typeof adding === "number" && !setId) {
              setCases([id]);
              advanceToBaseline();
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

type FocusParams = Pick<URLSearchParams, "get">;

function readFocus(focusParams?: FocusParams) {
  const readId = (key: string) => {
    const raw = focusParams?.get(key);
    const id = Number(raw);
    return raw && /^\d+$/.test(raw) && Number.isSafeInteger(id) && id > 0 ? id : undefined;
  };
  const focus = { agent: readId("agent_id"), version: readId("version_no"), suggestion: readId("suggestion_id"),
    candidate: readId("candidate_id"), experiment: readId("experiment_id"), evaluationSet: readId("set_id") };
  return { focus, feedback: readId("feedback_id") };
}

export function EvolutionWorkspace({ focusParams }: { focusParams?: FocusParams }) {
  const { focus, feedback } = readFocus(focusParams);
  const direction = focus.suggestion || focus.candidate ? "skill" : readEvolutionDirection(focusParams?.get("direction"));
  return direction || focus.experiment || focusParams?.get("open_cases") === "1" || feedback
    ? <EvolutionExperiments focusParams={focusParams} direction={direction} />
    : <EvolutionDirectionGuide scope={focus} />;
}

export default function EvolutionExperiments({ focusParams, direction }: { focusParams?: FocusParams; direction?: EvolutionDirection }) {
  const { user } = useAuthorizationContext();
  if (!user) return null;
  const viewer = JSON.stringify([user.tenantId, user.id]);
  const { focus, feedback } = readFocus(focusParams);
  return <>
    <AgentPicker key={`${viewer}:${direction ?? ""}:${focus.evaluationSet ?? ""}`} viewer={viewer} focus={focus} direction={direction} />
    {feedback && <ResourceHandoff key={`${viewer}:${feedback}`} id={feedback}
      script={focusParams?.get("feedback_kind") === "script"} />}
  </>;
}

function ResourceHandoff({ id, script }: { id: number; script: boolean }) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(true);
  return <Modal centered open={open} title={t(script ? "evolution.workflow.scriptTitle" : "evolution.workflow.generateTitle")}
    footer={null} onCancel={() => setOpen(false)} destroyOnHidden>
    {script ? <ScriptDraftForm feedbackId={id} /> : <ResourceCandidateGenerator feedbackId={id} />}
  </Modal>;
}

function AgentPicker({ viewer, focus, direction }: { viewer: string; focus: ComparisonFocus; direction?: EvolutionDirection }) {
  const { t } = useTranslation("common");
  const [agent, setAgent] = useState<number | undefined>(focus.agent);
  const [configuredVersion, setVersion] = useState<number | undefined>(focus.agent ? focus.version : undefined);
  const [toolMaintenanceOpen, setToolMaintenanceOpen] = useState(false);
  const agents = useQuery({
    queryKey: ["evolution-agents", viewer],
    queryFn: api.agents,
  });
  const versions = useQuery({
    queryKey: ["evolution-versions", viewer, agent],
    queryFn: () => api.versions(agent!),
    enabled: !!agent,
  });
  const current = agents.data?.find((item) => item.agent_id === agent)?.current_version_no;
  const version = configuredVersion ?? (current && current > 0 ? current : undefined);
  const validScope = version && versions.data?.some((item) => item.version_no === version);
  const error = agents.error || versions.error;
  return (
    <Flex vertical gap={16}>
      {direction && <Flex vertical gap={6}>
        <Link href={evolutionHref(undefined, { agent, version, evaluationSet: agent === focus.agent ? focus.evaluationSet : undefined })} className="self-start text-primary hover:underline">
          {t("evolution.direction.back")}
        </Link>
        <Typography.Title level={4} className="!m-0">{t(`evolution.direction.${direction}`)}</Typography.Title>
      </Flex>}
      {error instanceof Error && <Alert type="error" message={error.message} />}
      <Card size="small" title={t("evolution.workflow.scope")}
        extra={(!direction || direction === "tool") &&
          <Button type="link" onClick={() => setToolMaintenanceOpen(true)}>{t("evolution.workflow.toolMaintenance")}</Button>}>
      <Flex vertical gap={12}>
      <Typography.Text type="secondary">{t("evolution.workflow.scopeHelp")}</Typography.Text>
      <Flex gap={8} wrap>
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
          showSearch
          optionFilterProp="label"
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
      </Flex>
      </Card>
      {agent && version && validScope && (
        <Experiments
          key={`${agent}:${version}`}
          agent={agent}
          version={version}
          viewer={viewer}
          focus={agent === focus.agent && version === focus.version ? focus : undefined}
          direction={direction}
        />
      )}
      <Modal centered open={toolMaintenanceOpen} title={t("evolution.workflow.toolMaintenance")}
        footer={null} onCancel={() => setToolMaintenanceOpen(false)} destroyOnHidden>
        <ToolMaintainerBrief viewer={viewer} />
      </Modal>
    </Flex>
  );
}
