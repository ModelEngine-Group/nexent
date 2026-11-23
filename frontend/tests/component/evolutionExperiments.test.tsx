// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import EvolutionExperiments from "@/app/evaluation/components/EvolutionExperiments";
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
