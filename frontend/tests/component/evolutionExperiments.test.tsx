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
  vi.mocked(evolutionService.evaluators).mockResolvedValue([]);
  vi.mocked(evolutionService.workspace).mockResolvedValue({
    candidates: [],
    cases: [{ case_id: 9, family: "Owners", query: "List" }],
    experiments: [{ experiment_id: 42, create_time: "2026-11-23T00:00:00Z" }],
  });
  vi.mocked(evolutionService.report).mockResolvedValue({
    experiment_id: 42,
    status: "finished",
    total_pairs: 1,
    valid_pairs: 1,
    pairs: {
      "9": {
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
  await choose(
    "evolution.history",
    "#42 · " + new Date("2026-11-23T00:00:00Z").toLocaleString()
  );
  expect(await screen.findByText("unassigned")).toBeInTheDocument();
  expect(screen.getByText("missing owner")).toBeInTheDocument();
  expect(screen.getByText("evolution.state.improved")).toBeInTheDocument();
  expect(evolutionService.workspace).toHaveBeenCalledWith(7, 1);
  expect(evolutionService.submit).not.toHaveBeenCalled();
});
