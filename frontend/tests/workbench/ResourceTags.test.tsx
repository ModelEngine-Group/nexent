import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import {
  act,
  renderHook as originalRenderHook,
  waitFor,
} from "@testing-library/react";
import { useResourceTags } from "@/features/workbench/hooks/useResourceTags";
import { tagManagementApi } from "@/services/tagManagementService";
const renderHook: typeof originalRenderHook = (callback, options) => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return originalRenderHook(callback, {
    ...options,
    wrapper: ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client }, children),
  });
};
vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: {
    listLibraries: vi.fn().mockResolvedValue([]),
    listDefinitions: vi.fn(),
    filterResourceIds: vi.fn(),
  },
}));
beforeEach(() => vi.clearAllMocks());

it("batches authorized candidates in groups of 500", async () => {
  vi.mocked(tagManagementApi.filterResourceIds).mockImplementation(
    async (type, ids) => ({ resource_type: type, matched_resource_ids: ids })
  );
  const ids = Array.from({ length: 1001 }, (_, i) => String(i));
  const { result } = renderHook(() => useResourceTags(true, "skill", ids));
  act(() =>
    result.current.setPredicates([{ definition_id: 1, value_ids: [1] }])
  );
  await waitFor(() => expect(result.current.visibleIds?.size).toBe(1001));
  expect(
    vi
      .mocked(tagManagementApi.filterResourceIds)
      .mock.calls.map((call) => call[1].length)
  ).toEqual([500, 500, 1]);
});

it("server filtering retains predicates without expanding or locally querying a repository page", async () => {
  const { result } = renderHook(() => useResourceTags(true, "agent", [], true));
  const predicates = [{ definition_id: 1, value_ids: [1] }];
  act(() => result.current.setPredicates(predicates));
  expect(result.current.predicates).toEqual(predicates);
  expect(result.current.visibleIds).toBeNull();
  expect(tagManagementApi.filterResourceIds).not.toHaveBeenCalled();
});

it("empty authorized resources do not issue a filter request", async () => {
  const { result } = renderHook(() =>
    useResourceTags(true, "knowledge_base", [])
  );
  act(() =>
    result.current.setPredicates([{ definition_id: 1, value_ids: [1] }])
  );
  await waitFor(() => expect(result.current.visibleIds).toEqual(new Set()));
  expect(tagManagementApi.filterResourceIds).not.toHaveBeenCalled();
});

it("filter errors fail closed and clearing the filter restores authorized candidates", async () => {
  vi.mocked(tagManagementApi.filterResourceIds).mockRejectedValue(
    new Error("unavailable")
  );
  const { result } = renderHook(() => useResourceTags(true, "agent", ["A"]));
  act(() =>
    result.current.setPredicates([{ definition_id: 1, value_ids: [1] }])
  );
  await waitFor(() => expect(result.current.error).toBeTruthy());
  expect(result.current.visibleIds).toEqual(new Set());
  act(() => result.current.setPredicates([]));
  expect(result.current.visibleIds).toBeNull();
});

it.each(["agent", "skill", "knowledge_base"] as const)(
  "UT-FE-WB-038 %s tag results cannot expand authorized candidates",
  async (type) => {
    vi.mocked(tagManagementApi.filterResourceIds).mockResolvedValue({
      resource_type: type,
      matched_resource_ids: ["A", "X"],
    });
    const selected = new Set(["B"]);
    const config = { skill_mounts: [{ skill_id: 2, config_values: {} }] };
    const original = structuredClone(config);
    const { result } = renderHook(() =>
      useResourceTags(true, type, ["A", "B"])
    );
    const predicates = [
      { definition_id: 1, value_ids: [1, 2] },
      { definition_id: 2, value_ids: [3] },
    ];
    act(() => result.current.setPredicates(predicates));
    await waitFor(() =>
      expect(result.current.visibleIds).toEqual(new Set(["A"]))
    );
    expect(tagManagementApi.filterResourceIds).toHaveBeenCalledWith(
      type,
      ["A", "B"],
      predicates
    );
    expect(selected).toEqual(new Set(["B"]));
    act(() => result.current.setPredicates([]));
    await waitFor(() => expect(result.current.visibleIds).toBeNull());
    expect(config).toEqual(original);
  }
);

it("stale tag responses cannot overwrite a newer filter", async () => {
  let finish!: (value: {
    resource_type: string;
    matched_resource_ids: string[];
  }) => void;
  vi.mocked(tagManagementApi.filterResourceIds).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  const { result } = renderHook(() =>
    useResourceTags(true, "agent", ["A", "B"])
  );
  act(() =>
    result.current.setPredicates([{ definition_id: 1, value_ids: [1] }])
  );
  act(() => result.current.setPredicates([]));
  await act(async () => {
    finish({ resource_type: "agent", matched_resource_ids: ["A"] });
  });
  expect(result.current.visibleIds).toBeNull();
});
