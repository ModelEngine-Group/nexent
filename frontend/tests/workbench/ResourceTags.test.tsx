import { expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useResourceTags } from "@/features/workbench/hooks/useResourceTags";
import { tagManagementApi } from "@/services/tagManagementService";
vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: {
    listLibraries: vi.fn().mockResolvedValue([]),
    listDefinitions: vi.fn(),
    filterResourceIds: vi.fn(),
  },
}));

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
