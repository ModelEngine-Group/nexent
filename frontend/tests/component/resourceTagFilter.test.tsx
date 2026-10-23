// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { createQueryWrapper, render } from "./resourceDrawerTestUtils";
import { useResourceTagFilter } from "@/hooks/useResourceTagFilter";
import { AgentDrawer } from "@/components/resource-picker/AgentDrawer";
import { tagManagementApi } from "@/services/tagManagementService";
import type {
  TagDefinition,
  TagResourceFilterResult,
} from "@/types/tagManagement";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));
vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: {
    listLibraries: vi.fn(),
    listDefinitions: vi.fn(),
    filterResourceIds: vi.fn(),
    getAssignments: vi.fn(),
    getAgentAssignmentsBatch: vi.fn(async () => []),
  },
}));

const definition = {
  definition_id: 8,
  bucket_id: 1,
  definition_key: "department",
  definition_name: "Department",
  selection_mode: "multi_select",
  status: "active",
  sort_order: 0,
  active_value_count: 1,
  value_capacity: 100,
  values: [
    {
      value_id: 9,
      display_value: "Finance",
      normalized_value: "finance",
      sort_order: 0,
      status: "active",
    },
  ],
} as TagDefinition;
const rules = [{ definition_id: 8, value_ids: [9] }];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(tagManagementApi.filterResourceIds).mockReset();
  vi.mocked(tagManagementApi.listLibraries).mockResolvedValue([
    {
      bucket_id: 1,
      bucket_key: "default_resource",
      bucket_name: "Resources",
      status: "active",
      resource_types: ["agent", "skill", "knowledge_base", "tool"],
      definition_count: 1,
      definition_capacity: 100,
    },
  ]);
  vi.mocked(tagManagementApi.listDefinitions).mockResolvedValue([definition]);
  vi.mocked(tagManagementApi.getAssignments).mockResolvedValue({
    assignments: [],
  } as never);
  vi.mocked(tagManagementApi.filterResourceIds).mockResolvedValue({
    resource_type: "agent",
    matched_resource_ids: ["2", "unauthorized"],
  });
});

it("opens the shared group/value popover, filters original IDs and preserves the selection draft", async () => {
  const user = userEvent.setup();
  const confirm = vi.fn();
  render(
    <AgentDrawer
      open
      onClose={vi.fn()}
      onConfirm={confirm}
      selected={[]}
      categories={[
        {
          key: "local",
          label: "Local",
          items: [
            {
              id: "internal-1",
              agentId: 1,
              name: "First agent",
              description: "",
            },
            {
              id: "internal-2",
              agentId: 2,
              name: "Second agent",
              description: "",
            },
          ],
        },
      ]}
    />
  );
  await user.click(screen.getByRole("option", { name: "First agent" }));
  await waitFor(() =>
    expect(tagManagementApi.listDefinitions).toHaveBeenCalled()
  );
  await user.click(
    screen.getByRole("button", { name: "repository.tagFilter.button" })
  );
  const tagInputs = () =>
    screen
      .getAllByRole("combobox")
      .filter((input) => !input.closest('[data-picker-part="pagination"]'));
  await waitFor(() => expect(tagInputs()).toHaveLength(2));
  await user.click(tagInputs()[1]);
  await user.click(
    screen.getByText("Finance", { selector: ".ant-select-item-option-content" })
  );
  await waitFor(() =>
    expect(tagManagementApi.filterResourceIds).toHaveBeenCalledWith(
      "agent",
      ["1", "2"],
      rules
    )
  );
  await waitFor(() =>
    expect(screen.queryByRole("option", { name: "First agent" })).toBeNull()
  );
  expect(
    screen.getByRole("option", { name: "Second agent" })
  ).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "repository.tagFilter.clear" })
  );
  expect(
    await screen.findByRole("option", { name: "First agent" })
  ).toHaveAttribute("aria-selected", "true");
  await user.click(screen.getByRole("button", { name: "确认" }));
  expect(confirm).toHaveBeenCalledWith([
    { id: "internal-1", label: "First agent" },
  ]);
});

it("fails closed on a filter error and restores the authorized list on clear", async () => {
  vi.mocked(tagManagementApi.filterResourceIds).mockRejectedValue(
    new Error("unavailable")
  );
  const { result } = renderHook(
    () => useResourceTagFilter(true, "skill", ["1", "2"]),
    { wrapper: createQueryWrapper() }
  );
  act(() => result.current.setPredicates(rules));
  await waitFor(() => expect(result.current.error).toBeTruthy());
  expect(result.current.matchedIds).toEqual(new Set());
  act(() => result.current.setPredicates([]));
  expect(result.current.matchedIds).toBeNull();
});

it("batches candidate IDs and intersects all server results with authorized candidates", async () => {
  vi.mocked(tagManagementApi.filterResourceIds).mockImplementation(
    async (_, ids) => ({
      resource_type: "tool",
      matched_resource_ids: [ids[0], "unauthorized"],
    })
  );
  const ids = Array.from({ length: 501 }, (_, index) => String(index));
  const { result } = renderHook(() => useResourceTagFilter(true, "tool", ids), {
    wrapper: createQueryWrapper(),
  });
  act(() => result.current.setPredicates(rules));
  await waitFor(() => expect(result.current.filtering).toBe(false));
  expect(result.current.matchedIds).toEqual(new Set(["0", "500"]));
  expect(tagManagementApi.filterResourceIds).toHaveBeenCalledTimes(2);
});

it("ignores stale responses after changing the selected tag values", async () => {
  let finish!: (value: TagResourceFilterResult) => void;
  vi.mocked(tagManagementApi.filterResourceIds).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  const { result } = renderHook(
    () => useResourceTagFilter(true, "agent", ["1", "2"]),
    { wrapper: createQueryWrapper() }
  );
  act(() => result.current.setPredicates(rules));
  await waitFor(() => expect(finish).toBeDefined());
  act(() =>
    result.current.setPredicates([{ definition_id: 8, value_ids: [10] }])
  );
  await waitFor(() =>
    expect(result.current.matchedIds).toEqual(new Set(["2"]))
  );
  await act(async () =>
    finish({ resource_type: "agent", matched_resource_ids: ["1"] })
  );
  expect(result.current.matchedIds).toEqual(new Set(["2"]));
});

it("resets conditions on close and never sends an empty candidate request", async () => {
  const { result, rerender } = renderHook(
    ({ open }) => useResourceTagFilter(open, "knowledge_base", []),
    { initialProps: { open: true }, wrapper: createQueryWrapper() }
  );
  act(() => result.current.setPredicates(rules));
  await waitFor(() => expect(result.current.filtering).toBe(false));
  expect(result.current.matchedIds).toEqual(new Set());
  expect(tagManagementApi.filterResourceIds).not.toHaveBeenCalled();
  rerender({ open: false });
  await waitFor(() => expect(result.current.predicates).toEqual([]));
});
