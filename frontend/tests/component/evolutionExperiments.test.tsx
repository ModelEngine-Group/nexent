// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import EvolutionExperiments from "@/app/evaluation/components/EvolutionExperiments";
import DiscoveryFeedback from "@/app/evaluation/components/DiscoveryFeedback";
import LocalEditFeedback from "@/app/evaluation/components/LocalEditFeedback";
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
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "zh" } }),
}));
vi.mock("@/services/evolutionService", () => ({
  evolutionService: {
    agents: vi.fn(),
    versions: vi.fn(),
    evaluators: vi.fn(),
    workspace: vi.fn(),
    report: vi.fn(),
    submit: vi.fn(),
    exampleCandidates: vi.fn(),
    shareDiscovery: vi.fn(),
    developmentCase: vi.fn(),
    shareLocalEdit: vi.fn(),
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
    pairs: {
      "9": {
        no_skill: { status: "fail", result: { answer: "omitted control", skill: {
          guide_reads: 0, listed: false, mounted_revision: null,
        } } },
        base: { status: "fail", result: { answer: "missing owner" } },
        result: { status: "pass", result: { answer: "unassigned" } },
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
  expect(screen.getByText("omitted control")).toBeInTheDocument();
  expect(screen.getByText("evolution.skillCoverage")).toBeInTheDocument();
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
  vi.mocked(evolutionService.submit).mockResolvedValue({ experiment_id: 42 });
  fireEvent.click(compare);
  await waitFor(() => expect(evolutionService.submit).toHaveBeenCalledWith(expect.objectContaining({
    suggestion_id: 17, suggestion_target_case_id: 10, case_ids: [9, 10], candidate_id: 5,
  })));
});

it("hands off a tool failure when the answer passed, with approved input and argument fields", async () => {
  vi.mocked(evolutionService.developmentCase).mockResolvedValue({ task: {
    query: "extract rows from the meeting", expected: "[]",
    tool_use: { rules: [{ name: "read", min_calls: 1, max_calls: 1, arguments: { mode: "rows" } }] },
  } });
  vi.mocked(evolutionService.shareLocalEdit).mockResolvedValue({ feedback_id: 33 });
  const trial = (passed: boolean) => ({ status: passed ? "pass" : "fail", result: {
    answer: "[]", judgment: { status: "pass" }, tool_use: { status: passed ? "pass" : "fail", checked: ["read"] },
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
    method: "T2", tool_name: "read", share_expected_arguments: ["mode"],
    failure: { case_id: 1, input_excerpt: "extract rows", expected: "[]", observed: "[]" },
    protection: { case_id: 2, input_excerpt: "extract rows", expected: "[]", observed: "[]" },
  })));
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
