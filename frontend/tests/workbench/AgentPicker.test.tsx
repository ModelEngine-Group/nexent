import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AgentPicker } from "@/features/workbench/components/AgentPicker";
import {
  fetchAgentRepositoryListings,
  fetchRepositoryImportPrecheck,
  importAgentFromRepository,
} from "@/services/agentRepositoryService";
import { fetchPublishedAgentList } from "@/services/agentConfigService";
import type { Agent } from "@/types/agentConfig";

vi.mock("@/services/agentRepositoryService", () => ({
  fetchAgentRepositoryListings: vi.fn(),
  fetchRepositoryImportPrecheck: vi.fn(),
  importAgentFromRepository: vi.fn(),
}));
vi.mock("@/services/agentConfigService", () => ({
  fetchPublishedAgentList: vi.fn(),
}));
vi.mock("@/features/workbench/hooks/useResourceTags", () => ({
  useResourceTags: () => ({
    definitions: [],
    predicates: empty,
    visibleIds: null,
  }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
const empty = vi.hoisted(() => []);
const agent = {
  id: "8",
  name: "Agent A",
  current_version_no: 3,
  is_available: true,
} as Agent;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchAgentRepositoryListings).mockResolvedValue({
    items: [
      { agent_repository_id: 20, name: "Repository A", status: "shared" },
    ],
  });
  vi.mocked(fetchRepositoryImportPrecheck).mockResolvedValue({
    agent_repository_id: 20,
    display_name: "Repository A",
    has_abnormal: false,
    available_count: 0,
    total_count: 0,
    percent: 100,
    items: [],
  });
  vi.mocked(importAgentFromRepository).mockResolvedValue({ agent_id: 99 });
});
function mount() {
  const onSelect = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AgentPicker
        open
        agents={[agent]}
        selectedId="7"
        onSelect={onSelect}
        onCancel={vi.fn()}
      />
    </QueryClientProvider>
  );
  return onSelect;
}
it("shows the backend unavailable reason and only one published version badge", async () => {
  const select = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AgentPicker
        open
        agents={[
          {
            ...agent,
            is_available: false,
            unavailable_reasons: ["Missing model dependency"],
          },
        ]}
        onSelect={select}
        onCancel={vi.fn()}
      />
    </QueryClientProvider>
  );
  const card = screen.getByRole("option", { name: "Agent A" });
  expect(card).toBeDisabled();
  expect(card).toHaveAccessibleDescription("Missing model dependency");
  expect(screen.getAllByText("v3")).toHaveLength(1);
  await userEvent.click(card);
  expect(select).not.toHaveBeenCalled();
});
it("UT-FE-WB-019 selecting a published Agent remains pending until confirmation", async () => {
  const select = mount();
  await userEvent.click(screen.getByRole("option", { name: /Agent A/ }));
  expect(select).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "确认选择" }));
  expect(select).toHaveBeenCalledExactlyOnceWith(agent);
  expect(importAgentFromRepository).not.toHaveBeenCalled();
});
it("multi-agent select-all remains pending and cancel does not apply it", async () => {
  const confirm = vi.fn();
  const cancel = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AgentPicker
        open
        multiple
        agents={[agent, { ...agent, id: "9", name: "Agent B" }]}
        onSelect={vi.fn()}
        onConfirm={confirm}
        onCancel={cancel}
      />
    </QueryClientProvider>
  );
  await userEvent.click(screen.getByRole("button", { name: "全选" }));
  expect(
    screen
      .getAllByRole("option")
      .every((card) => card.getAttribute("aria-selected") === "true")
  ).toBe(true);
  expect(confirm).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: /^取\s*消$/ }));
  expect(cancel).toHaveBeenCalledOnce();
  expect(confirm).not.toHaveBeenCalled();
});
it("UT-FE-WB-020 uses the returned root ID, never a name lookup", async () => {
  const imported = { ...agent, id: "99", name: "Renamed on import" };
  vi.mocked(fetchPublishedAgentList).mockResolvedValue({
    success: true,
    message: "",
    data: [agent, imported],
  });
  const select = mount();
  await userEvent.click(screen.getByRole("tab", { name: "仓库" }));
  await userEvent.click(
    await screen.findByRole("option", { name: /Repository A/ })
  );
  expect(importAgentFromRepository).not.toHaveBeenCalled();
  await userEvent.click(
    await screen.findByRole("button", { name: "导入并选择" })
  );
  await waitFor(() => expect(fetchPublishedAgentList).toHaveBeenCalledOnce());
  expect(select).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "确认选择" }));
  await waitFor(() => expect(select).toHaveBeenCalledExactlyOnceWith(imported));
  expect(fetchRepositoryImportPrecheck).toHaveBeenCalledWith(20);
  expect(importAgentFromRepository).toHaveBeenCalledExactlyOnceWith(20);
});
it("UT-FE-WB-021 an imported unavailable Agent is not automatically selected", async () => {
  vi.mocked(fetchPublishedAgentList).mockResolvedValue({
    success: true,
    message: "",
    data: [{ ...agent, id: "99", is_available: false }],
  });
  const select = mount();
  await userEvent.click(screen.getByRole("tab", { name: "仓库" }));
  await userEvent.click(
    await screen.findByRole("option", { name: /Repository A/ })
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "导入并选择" })
  );
  await waitFor(() => expect(fetchPublishedAgentList).toHaveBeenCalledOnce());
  expect(select).not.toHaveBeenCalled();
});

it("UT-FE-WB-038 resolves duplicate Skills before importing an Agent", async () => {
  vi.mocked(fetchRepositoryImportPrecheck).mockResolvedValue({
    agent_repository_id: 20,
    display_name: "Repository A",
    has_abnormal: true,
    available_count: 0,
    total_count: 1,
    percent: 0,
    items: [
      {
        type: "skill",
        key: "invoice",
        name: "Invoice Skill",
        available: false,
        reason_code: "skill_duplicate",
        suggested_new_name: "Invoice Skill 副本",
      },
    ],
  });
  vi.mocked(fetchPublishedAgentList).mockResolvedValue({
    success: true,
    message: "",
    data: [{ ...agent, id: "99" }],
  });
  mount();
  await userEvent.click(screen.getByRole("tab", { name: "仓库" }));
  await userEvent.click(
    await screen.findByRole("option", { name: /Repository A/ })
  );
  await userEvent.click(screen.getByLabelText("使用已有 Skill"));
  await userEvent.click(screen.getByRole("button", { name: "导入并选择" }));
  await waitFor(() =>
    expect(importAgentFromRepository).toHaveBeenCalledWith(20, [
      {
        skill_name: "Invoice Skill",
        action: "use_existing",
      },
    ])
  );
});

it("UT-FE-WB-038 ignores a stale precheck after switching tabs", async () => {
  let resolvePrecheck!: (
    value: Awaited<ReturnType<typeof fetchRepositoryImportPrecheck>>
  ) => void;
  vi.mocked(fetchRepositoryImportPrecheck).mockReturnValue(
    new Promise((resolve) => {
      resolvePrecheck = resolve;
    })
  );
  mount();
  await userEvent.click(screen.getByRole("tab", { name: "仓库" }));
  await userEvent.click(
    await screen.findByRole("option", { name: /Repository A/ })
  );
  await userEvent.click(screen.getByRole("tab", { name: "我的" }));
  resolvePrecheck({
    agent_repository_id: 20,
    display_name: "Repository A",
    has_abnormal: false,
    available_count: 0,
    total_count: 0,
    percent: 100,
    items: [],
  });
  await waitFor(() =>
    expect(screen.queryByText("导入预检")).not.toBeInTheDocument()
  );
  expect(importAgentFromRepository).not.toHaveBeenCalled();
});
