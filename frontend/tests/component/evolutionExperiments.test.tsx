// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import EvolutionExperiments from "@/app/evaluation/components/EvolutionExperiments";
import DiscoveryFeedback from "@/app/evaluation/components/DiscoveryFeedback";
import LocalEditFeedback from "@/app/evaluation/components/LocalEditFeedback";
import ToolSetCandidates from "@/app/evaluation/components/ToolSetCandidates";
import FixedRegressionCases from "@/app/evaluation/components/FixedRegressionCases";
import { evolutionService } from "@/services/evolutionService";

vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({
    user: { id: "editor", tenantId: "pilot" },
  }),
}));
vi.mock("@/hooks/model/useModelList", () => ({
  useModelList: () => ({ availableLlmModels: [] }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, args?: { experiment: number }) =>
      key === "evolution.sourceExperiment" ? key + "#" + args?.experiment : key,
    i18n: { language: "zh" },
  }),
}));
vi.mock("@/services/evolutionService", () => ({
  evolutionService: {
    agents: vi.fn(),
    versions: vi.fn(),
    evaluators: vi.fn(),
    workspace: vi.fn(),
    traceCaseDraft: vi.fn(),
    createCase: vi.fn(),
    report: vi.fn(),
    nominate: vi.fn(),
    submit: vi.fn(),
    exampleCandidates: vi.fn(),
    shareDiscovery: vi.fn(),
    developmentCase: vi.fn(),
    shareLocalEdit: vi.fn(),
    toolSetCandidates: vi.fn(),
    setFixedRegression: vi.fn(),
  },
}));

async function choose(label: string, option: string) {
  const select = await screen.findByRole("combobox", { name: label });
  fireEvent.mouseDown(select.closest(".ant-select-selector") || select);
  await waitFor(() => {
    const item = [
      ...document.querySelectorAll(".ant-select-item-option-content"),
    ].find((el) => el.textContent === option);
    expect(item).toBeTruthy();
    fireEvent.click(item!);
  });
}

it("selects a published scope and opens its paired results with the original statuses", async () => {
  vi.mocked(evolutionService.agents).mockResolvedValue([
    { agent_id: 7, name: "Meeting agent" },
  ]);
  vi.mocked(evolutionService.versions).mockResolvedValue([
    { version_no: 1, version_name: "Pilot" },
  ]);
  vi.mocked(evolutionService.evaluators).mockResolvedValue([
    { evaluator_id: 3, name: "Rules", evaluator_type: "code", status: "PUBLISHED" },
  ]);
  vi.mocked(evolutionService.workspace).mockResolvedValue({
    candidates: [{ candidate_id: 5, kind: "skill_step", name: "Skill" }],
    suggestions: [{ suggestion_id: 17, expected_behavior: "Keep sources", skill_id: 2, experiment_id: null }],
    cases: [{ case_id: 9, family: "Owners", query: "List" }, { case_id: 10, family: "Sources", query: "Extract" }],
    experiments: [{ experiment_id: 42, create_time: "2026-11-23T00:00:00Z" }],
    reviews: [{ turn_id: 3, batch_id: null, state: "observed", signals: ["tool_error"] }],
  });
  vi.mocked(evolutionService.report).mockResolvedValue({
    experiment_id: 42,
    status: "finished",
    total_pairs: 1,
    valid_pairs: 1,
    valid_triplets: 1,
    verified_guide_pairs: 0,
    screening: { status:"incomplete", gain:null, criteria:{metric:"tasks_fixed", minimum:1, target_case_ids:[9]},
      missing:{no_fixed_regression:[]}, failures:{} },
    pairs: {
      "9": {
        no_skill: { status: "fail", result: { answer: "omitted control", skill: {
          guide_reads: 0, listed: false, mounted_revision: null,
        } } },
        base: { status: "fail", result: { answer: "missing owner" } },
        result: { status: "pass", result: { answer: "unassigned", file_state: {
          status:"pass", missing:[], extra:[], wrong_content:[], protected_writes:[],
        } } },
        comparison: "improved",
      },
    },
  });
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <EvolutionExperiments />
    </QueryClientProvider>
  );
  await choose("agentEvaluation.agentLabel", "Meeting agent");
  await choose("agentEvaluation.agentVersionLabel", "V1 Pilot");
  fireEvent.click(await screen.findByText("evolution.recentObservations"));
  expect(screen.getByText(/evolution.observation.tool_error/)).toBeInTheDocument();
  await choose(
    "evolution.history",
    "#42 · " + new Date("2026-11-23T00:00:00Z").toLocaleString()
  );
  expect(await screen.findByText("unassigned")).toBeInTheDocument();
  expect(screen.getByText("evolution.fileVerdict")).toBeInTheDocument();
  expect(screen.getByText("omitted control")).toBeInTheDocument();
  expect(screen.getByText("evolution.skillCoverage")).toBeInTheDocument();
  expect(screen.getByText("evolution.screen.incomplete")).toBeInTheDocument();
  expect(screen.getByText("evolution.screen.no_fixed_regression")).toBeInTheDocument();
  expect(screen.getByText("missing owner")).toBeInTheDocument();
  expect(screen.getByText("evolution.state.improved")).toBeInTheDocument();
  expect(evolutionService.workspace).toHaveBeenCalledWith(7, 1);
  expect(evolutionService.submit).not.toHaveBeenCalled();
  vi.mocked(evolutionService.exampleCandidates).mockResolvedValue({
    variants: [{ candidate_id: null, example_count: 0 }, { candidate_id: 6, example_count: 1 }],
  });
  fireEvent.click(screen.getByRole("button", { name: "evolution.selectExamples" }));
  await choose("evolution.failedTarget", "Owners");
  await choose("evolution.passingTrial", "Owners · evolution.result");
  for (const [label, value] of [["targetBehavior", "name"], ["exampleBehavior", "name"],
    ["input_excerpt", "List"], ["output_excerpt", "unassigned"]]) {
    fireEvent.change(screen.getByLabelText("evolution." + label), { target: { value } });
  }
  fireEvent.click(screen.getByRole("button", { name: "evolution.generateExamples" }));
  await waitFor(() => expect(evolutionService.exampleCandidates).toHaveBeenCalledWith(42, {
    target_case_id: 9, target_behavior: "name", examples: [
      { case_id: 9, variant: "result", behavior: "name", input_excerpt: "List", output_excerpt: "unassigned" },
    ],
  }));
  fireEvent.click(await screen.findByRole("button", { name: "evolution.tryExampleCandidate" }));
  await choose("evolution.suggestion", "S-17 · Keep sources");
  await choose("evolution.candidate", "#5 · Skill");
  await choose("evolution.evaluator", "Rules");
  await choose("evolution.cases", "Owners · List");
  const compare = screen.getByRole("button", { name: "evolution.compare" });
  expect(compare).toBeDisabled();
  fireEvent.keyDown(screen.getByRole("combobox", { name: "evolution.cases" }), { key: "Escape" });
  await choose("evolution.cases", "Sources · Extract");
  expect(compare).toBeDisabled();
  await choose("evolution.suggestionTarget", "Sources");
  fireEvent.click(screen.getByRole("checkbox", {name:"evolution.screen.enable"}));
  expect(compare).toBeDisabled();
  await choose("evolution.screen.targets", "Extract");
  vi.mocked(evolutionService.submit).mockResolvedValue({ experiment_id: 42 });
  fireEvent.click(compare);
  await waitFor(() => expect(evolutionService.submit).toHaveBeenCalledWith(expect.objectContaining({
    suggestion_id: 17, suggestion_target_case_id: 10, case_ids: [9, 10], candidate_id: 5,
    screening: { target_case_ids:[10], metric:"tasks_fixed", minimum:1 },
  })));
});

it("submits an eligible candidate only when its editor requests independent confirmation", async () => {
  vi.mocked(evolutionService.agents).mockResolvedValue([{agent_id:7,name:"Meeting agent"}]);
  vi.mocked(evolutionService.versions).mockResolvedValue([{version_no:1,version_name:"Pilot"}]);
  const date = "2026-11-23T00:00:00Z";
  vi.mocked(evolutionService.workspace).mockResolvedValue({cases:[],candidates:[],experiments:[{experiment_id:41,create_time:date}]});
  vi.mocked(evolutionService.report).mockResolvedValue({experiment_id:41,status:"finished",valid_pairs:2,total_pairs:2,pairs:{},
    screening:{status:"eligible",gain:1,criteria:{target_case_ids:[2],metric:"tasks_fixed",minimum:1},failures:{},missing:{}}});
  const digest = "b".repeat(64);
  vi.mocked(evolutionService.nominate).mockResolvedValue({experiment_id:41,candidate_digest:digest});
  render(<QueryClientProvider client={new QueryClient()}><EvolutionExperiments /></QueryClientProvider>);
  await choose("agentEvaluation.agentLabel", "Meeting agent");
  await choose("agentEvaluation.agentVersionLabel", "V1 Pilot");
  await choose("evolution.history", "#41 · " + new Date(date).toLocaleString());
  const submit = await screen.findByRole("button", {name:"evolution.confirmation.submit"});
  expect(evolutionService.nominate).not.toHaveBeenCalled();
  fireEvent.click(submit);
  expect(await screen.findByText(digest)).toBeInTheDocument();
  expect(evolutionService.nominate).toHaveBeenCalledWith(41);
});

it("requires a business expectation before freezing a trace draft, then selects its baseline", async () => {
  vi.mocked(evolutionService.agents).mockResolvedValue([{ agent_id: 7, name: "Meeting agent" }]);
  vi.mocked(evolutionService.versions).mockResolvedValue([{ version_no: 1, version_name: "Pilot" }]);
  vi.mocked(evolutionService.workspace).mockResolvedValue({ candidates: [], cases: [], experiments: [],
    reviews: [{turn_id: 3, batch_id: 1, state: "observed", signals: ["user_correction"]}] });
  vi.mocked(evolutionService.traceCaseDraft).mockResolvedValue({ turn_id: 3, draft_digest: "a".repeat(64),
    trajectory_id: "scope-run", attachment_count: 0, tool_count: 1, tools: [], signals: [], query: "Summarize the minutes." });
  vi.mocked(evolutionService.createCase).mockResolvedValue({ case_id: 12 });
  render(<QueryClientProvider client={new QueryClient()}><EvolutionExperiments /></QueryClientProvider>);
  await choose("agentEvaluation.agentLabel", "Meeting agent");
  await choose("agentEvaluation.agentVersionLabel", "V1 Pilot");
  fireEvent.click(await screen.findByText("evolution.recentObservations"));
  fireEvent.click(screen.getByRole("button", { name: "evolution.makeTraceCase" }));
  expect(await screen.findByDisplayValue("Summarize the minutes.")).toBeInTheDocument();
  const save = screen.getByRole("button", { name: "evolution.saveCase" });
  expect(save).toBeDisabled();
  fireEvent.change(screen.getByLabelText("evolution.family"), { target: { value: "meeting" } });
  fireEvent.change(screen.getByLabelText("evolution.query"), { target: { value: "List synthetic actions" } });
  fireEvent.change(screen.getByLabelText("evolution.expected"), { target: { value: "Keep unassigned items" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "evolution.traceApproval" }));
  expect(save).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: "evolution.verifyFiles" }));
  fireEvent.click(screen.getByRole("button", { name: "evolution.addFileRule" }));
  fireEvent.change(screen.getByLabelText("evolution.fileName"), {target:{value:"actions.txt"}});
  fireEvent.change(screen.getByLabelText("evolution.fileBefore"), {target:{value:"draft"}});
  fireEvent.change(screen.getByLabelText("evolution.fileAfter"), {target:{value:"ready"}});
  fireEvent.click(screen.getByRole("button", { name: "evolution.addTurn" }));
  fireEvent.change(screen.getByLabelText("evolution.followup"), { target: { value: "Add a source to each row" } });
  fireEvent.click(save);
  await waitFor(() => expect(evolutionService.createCase).toHaveBeenCalledWith(expect.objectContaining({
    query: "List synthetic actions", expected: "Keep unassigned items", agent_id: 7, version_no: 1,
    followups: [{query: "Add a source to each row"}],
    file_state: {adapter:"text-files-v1", initial:{"actions.txt":"draft"}, expected:{"actions.txt":"ready"}, protected:[]},
    trace: { turn_id: 3, purpose: "reproduce", draft_digest: "a".repeat(64),
      inputs_reviewed: true, tools_require_no_reset: false, unused_attachment_slots: [], use_previous_task: false },
  })));
  expect(await screen.findByText("evolution.baselineSelection")).toBeInTheDocument();
});

it("combines two finished single experiments in selection order and shows the four outcomes", async () => {
  vi.mocked(evolutionService.agents).mockResolvedValue([{ agent_id: 7, name: "Meeting agent" }]);
  vi.mocked(evolutionService.versions).mockResolvedValue([{ version_no: 1, version_name: "Pilot" }]);
  vi.mocked(evolutionService.evaluators).mockResolvedValue([
    { evaluator_id: 3, name: "Rules", evaluator_type: "code", status: "PUBLISHED" },
  ]);
  const components = [
    { experiment_id: 9, candidate_id: 5, candidate_type: "tool_set" },
    { experiment_id: 8, candidate_id: 4, candidate_type: "prompt" },
  ];
  vi.mocked(evolutionService.workspace).mockResolvedValue({
    candidates: [], cases: [{ case_id: 13, family: "Meeting", query: "List actions" }],
    experiments: components.map(part => ({ ...part, create_time: "2026-11-23", eligible_component: true })),
  });
  const passed = { status: "pass" };
  const failed = { status: "fail" };
  vi.mocked(evolutionService.report).mockResolvedValue({
    experiment_id: 12, status: "finished", components, valid_pairs: 2, total_pairs: 2, valid_quartets: 2,
    pairs: {
      "13": { base: failed, only_a: failed, only_b: failed, result: passed, comparison: "improved",
        combination: { effect: "joint_only", a_vs_base: "both_fail", b_vs_base: "both_fail",
          combined_vs_a: "improved", combined_vs_b: "improved" } },
      "14": { base: passed, only_a: passed, only_b: passed, result: failed, comparison: "regressed",
        combination: { effect: "lost_single_pass", a_vs_base: "both_pass", b_vs_base: "both_pass",
          combined_vs_a: "regressed", combined_vs_b: "regressed" } },
    },
  });
  vi.mocked(evolutionService.submit).mockResolvedValue({ experiment_id: 12 });
  render(<QueryClientProvider client={new QueryClient()}><EvolutionExperiments /></QueryClientProvider>);
  await choose("agentEvaluation.agentLabel", "Meeting agent");
  await choose("agentEvaluation.agentVersionLabel", "V1 Pilot");
  await choose("evolution.candidate", "evolution.combination");
  await choose("evolution.evaluator", "Rules");
  await choose("evolution.cases", "Meeting · List actions");
  fireEvent.keyDown(screen.getByRole("combobox", { name: "evolution.cases" }), { key: "Escape" });
  await choose("evolution.chooseComponents", "evolution.sourceExperiment#9");
  const compare = screen.getByRole("button", { name: "evolution.compare" });
  expect(compare).toBeDisabled();
  fireEvent.keyDown(screen.getByRole("combobox", { name: "evolution.chooseComponents" }), { key: "Escape" });
  await choose("evolution.chooseComponents", "evolution.sourceExperiment#8");
  fireEvent.click(compare);
  await waitFor(() => expect(evolutionService.submit).toHaveBeenCalledWith(expect.objectContaining({
    candidate_type: "combination", case_ids: [13], components,
  })));
  expect(await screen.findByText("evolution.quartets")).toBeInTheDocument();
  for (const key of ["base", "only_a", "only_b", "combinedAB"]) {
    expect(screen.getByRole("columnheader", { name: "evolution." + key })).toBeInTheDocument();
  }
  expect(screen.getByText(/evolution.effect.joint_only/)).toBeInTheDocument();
  expect(screen.getByText(/evolution.effect.lost_single_pass/)).toBeInTheDocument();
});

it("hands off a tool failure when the answer passed, with approved input and argument fields", async () => {
  vi.mocked(evolutionService.developmentCase).mockResolvedValue({ task: {
    query: "extract rows from the meeting", expected: "[]",
    tool_use: { rules: [{ name: "read", min_calls: 1, max_calls: 1, arguments: { mode: "rows" } }] },
  } });
  vi.mocked(evolutionService.shareLocalEdit).mockResolvedValue({ feedback_id: 33 });
  const trial = (passed: boolean) => ({ status: passed ? "pass" : "fail", result: {
    answer: "[]", judgment: { status: "pass" }, tool_use: { status: passed ? "pass" : "fail", checked: ["read"] },
    file_state: {status:passed ? "pass" : "fail", missing:[], extra:[], wrong_content:passed ? [] : ["rows.txt"], protected_writes:[]},
  } });
  render(<QueryClientProvider client={new QueryClient()}><LocalEditFeedback viewer="tenant-editor" agent={1} version={1}
    workspace={{ candidates: [], experiments: [], cases: [
      { case_id: 1, query: "incorrect argument", family: "tool" }, { case_id: 2, query: "correct argument", family: "tool" },
    ] }} report={{ experiment_id: 24, status: "finished", total_pairs: 0, valid_pairs: 0, pairs: {
      "1": { base: trial(false), comparison: "baseline_only" }, "2": { base: trial(true), comparison: "baseline_only" },
    } }} /></QueryClientProvider>);
  fireEvent.click(screen.getByRole("button", { name: "evolution.shareLocalEdit" }));
  await choose("evolution.editMethod", "evolution.method.T2");
  await choose("evolution.feedback.failure", "incorrect argument");
  await choose("evolution.feedback.protection", "correct argument");
  await choose("evolution.toolName", "read");
  const shareFiles = screen.getByRole("checkbox", {name:"evolution.shareFileChecks"});
  expect(shareFiles).not.toBeChecked();
  fireEvent.click(shareFiles);
  await choose("evolution.shareArgumentValues", "mode");
  fireEvent.keyDown(screen.getByRole("combobox", { name: "evolution.shareArgumentValues" }), { key: "Escape" });
  for (const [label, value] of [["editGoal","respect supplied mode"],["sourcePassage","read the meeting"]]) {
    fireEvent.change(screen.getByLabelText("evolution." + label), { target: { value } });
  }
  for (const [label, value] of [["input_excerpt","extract rows"],["expected","[]"],["observed","[]"]]) {
    for (const el of screen.getAllByLabelText("evolution.excerpt." + label)) {
      fireEvent.change(el, { target: { value } });
    }
  }
  fireEvent.click(screen.getByRole("button", { name: "evolution.shareFeedback" }));
  await waitFor(() => expect(evolutionService.shareLocalEdit).toHaveBeenCalledWith(24, expect.objectContaining({
    method: "T2", tool_name: "read", share_expected_arguments: ["mode"], share_file_state: true,
    failure: { case_id: 1, input_excerpt: "extract rows", expected: "[]", observed: "[]" },
    protection: { case_id: 2, input_excerpt: "extract rows", expected: "[]", observed: "[]" },
  })));
});

it("requires both an unwanted call and a protection case before trying a narrower tool set", async () => {
  const select = vi.fn();
  vi.mocked(evolutionService.toolSetCandidates).mockResolvedValue({ variants: [
    { candidate_id: null, removed: [], retained: ["search"] }, { candidate_id: 27, removed: ["search"], retained: [] },
  ] });
  const trial = (status: string, max_calls: number) => ({ base: { status, result: { tool_use: {
    status, issues: status === "fail" ? [{ reason: "too_many", tool: "search", max_calls }] : [],
  } } }, comparison: "baseline_only" });
  render(<QueryClientProvider client={new QueryClient()}><ToolSetCandidates onSelect={select}
    cases={[{ case_id: 1, family: "tools", query: "skip search" }, { case_id: 2, family: "tools", query: "read guide" }]}
    report={{ experiment_id: 55, status: "finished", total_pairs: 0, valid_pairs: 0,
      pairs: { "1": trial("fail", 0), "2": trial("pass", 1), "3": trial("fail", 2) } }} /></QueryClientProvider>);
  fireEvent.click(screen.getByText("evolution.proposeToolSets"));
  const generate = screen.getByRole("button", { name: "evolution.generateToolSets" });
  expect(generate).toBeDisabled();
  await choose("evolution.excessCalls", "skip search");
  fireEvent.keyDown(screen.getByRole("combobox", { name: "evolution.excessCalls" }), { key: "Escape" });
  expect(generate).toBeDisabled();
  await choose("evolution.protectTools", "read guide");
  fireEvent.keyDown(screen.getByRole("combobox", { name: "evolution.protectTools" }), { key: "Escape" });
  fireEvent.click(generate);
  fireEvent.click(await screen.findByRole("button", { name: "evolution.tryToolSet" }));
  expect(evolutionService.toolSetCandidates).toHaveBeenCalledWith(55, [1], [2]);
  expect(select).toHaveBeenCalledWith(27);
});

it("maintains the shared regression suite from a published version", async () => {
  const refresh = vi.fn().mockResolvedValue(undefined);
  vi.mocked(evolutionService.setFixedRegression).mockResolvedValue({ case_id: 13, enabled: true });
  render(<QueryClientProvider client={new QueryClient()}><FixedRegressionCases agent={7} version={2}
    models={[]} rubrics={[{ evaluator_id: 15, name: "owner rule", evaluator_type: "code" }]}
    workspace={{ experiments: [], candidates: [], cases: [{ case_id: 13, digest: "new", family: "minutes", query: "all owners" }],
      fixed_regression: [{ source_case_id: 9, source_version: 1, digest: "old", family: "minutes", query: "protect read" }] }}
    refresh={refresh} /></QueryClientProvider>);
  fireEvent.click(screen.getByText("evolution.fixedSuite"));
  await choose("evolution.chooseFixed", "minutes · all owners");
  expect(screen.getByRole("button", { name: "evolution.addFixed" })).toBeDisabled();
  await choose("evolution.fixedRubric", "owner rule");
  fireEvent.click(screen.getByRole("button", { name: "evolution.addFixed" }));
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "evolution.removeFixed" }));
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(2));
  expect(evolutionService.setFixedRegression).toHaveBeenNthCalledWith(1, 7, 2, 13, true, { evaluator_id: 15, language: "zh", judge_model_id: undefined });
  expect(evolutionService.setFixedRegression).toHaveBeenNthCalledWith(2, 7, 1, 9, false, undefined);
});

it("shares only the three approved request excerpts for a discovery rewrite", async () => {
  const groups = ["missed", "overused", "correct"];
  const tasks = groups.map((name, i) => ({ case_id: i + 1, family: name, query: name + " meeting" }));
  const reads: Record<string, number>[] = [{}, { meeting: 1 }, { meeting: 1 }];
  const report = {
    experiment_id: 23, status: "finished", valid_pairs: 0, total_pairs: 0,
    pairs: Object.fromEntries(tasks.map((c, i) => [String(c.case_id), {
      comparison: "baseline_only", base: { status: "pass", result: {
        answer: "private answer", selection: { expected: i === 1 ? [] : ["meeting"],
          reads: reads[i], outcome: ["missed", "wrong", "hit"][i] },
      } },
    }])),
  };
  vi.mocked(evolutionService.shareDiscovery).mockResolvedValue({ feedback_id: 27 });
  render(<QueryClientProvider client={new QueryClient()}><DiscoveryFeedback report={report}
    workspace={{ skills: [{ name: "meeting", skill_id: 12 }], cases: tasks, candidates: [], experiments: [] }} />
    </QueryClientProvider>);
  fireEvent.click(screen.getByText("evolution.discoveryFeedback"));
  await choose("evolution.targetSkill", "meeting");
  fireEvent.change(screen.getByLabelText("evolution.discoveryGoal"), { target: { value: "change trigger" } });
  for (const [i, group] of groups.entries()) {
    await choose(`evolution.group.${group}`, tasks[i].query);
  }
  fireEvent.change(screen.getAllByLabelText("evolution.approvedExcerpt")[0], { target: { value: "missed" } });
  fireEvent.click(screen.getByRole("button", { name: "evolution.shareFeedback" }));
  await waitFor(() => expect(evolutionService.shareDiscovery).toHaveBeenCalledWith(23, {
    method: "S1", skill_id: 12, goal: "change trigger",
    missed: { case_id: 1, query_excerpt: "missed" },
    overused: { case_id: 2, query_excerpt: "overused meeting" },
    correct: { case_id: 3, query_excerpt: "correct meeting" },
  }));
});
