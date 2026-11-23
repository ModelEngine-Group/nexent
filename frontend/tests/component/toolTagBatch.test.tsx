// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { renderHook, waitFor, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { createQueryWrapper, render } from "./resourceDrawerTestUtils";
import { useToolTagAssignments } from "@/hooks/useToolTagAssignments";
import { ResourceAssignedTags } from "@/components/resource-picker/ResourceAssignedTags";
import { tagManagementApi } from "@/services/tagManagementService";
import type { TagAssignment } from "@/types/tagManagement";

vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: {
    getToolAssignmentsBatch: vi.fn(),
    getAssignments: vi.fn(),
  },
}));

beforeEach(() => vi.resetAllMocks());

it("reads each visible page once and refreshes after a label revision", async () => {
  vi.mocked(tagManagementApi.getToolAssignmentsBatch).mockResolvedValue([]);
  const view = renderHook(
    ({ open, ids, revision }) => useToolTagAssignments(open, ids, revision),
    {
      initialProps: { open: false, ids: ["1", "2"], revision: 0 },
      wrapper: createQueryWrapper(),
    }
  );
  expect(tagManagementApi.getToolAssignmentsBatch).not.toHaveBeenCalled();
  view.rerender({ open: true, ids: ["1", "2"], revision: 0 });
  await waitFor(() => expect(view.result.current.isSuccess).toBe(true));
  expect(
    tagManagementApi.getToolAssignmentsBatch
  ).toHaveBeenCalledExactlyOnceWith(["1", "2"]);
  view.rerender({ open: true, ids: ["1", "2"], revision: 0 });
  expect(tagManagementApi.getToolAssignmentsBatch).toHaveBeenCalledTimes(1);
  view.rerender({ open: true, ids: ["3"], revision: 0 });
  await waitFor(() =>
    expect(tagManagementApi.getToolAssignmentsBatch).toHaveBeenCalledTimes(2)
  );
  expect(tagManagementApi.getToolAssignmentsBatch).toHaveBeenLastCalledWith([
    "3",
  ]);
  view.rerender({ open: true, ids: ["3"], revision: 1 });
  await waitFor(() =>
    expect(tagManagementApi.getToolAssignmentsBatch).toHaveBeenCalledTimes(3)
  );
  view.rerender({ open: true, ids: [], revision: 1 });
  expect(tagManagementApi.getToolAssignmentsBatch).toHaveBeenCalledTimes(3);
  view.rerender({ open: false, ids: ["3"], revision: 1 });
  view.rerender({ open: true, ids: ["3"], revision: 1 });
  await waitFor(() =>
    expect(tagManagementApi.getToolAssignmentsBatch).toHaveBeenCalledTimes(4)
  );
  expect(tagManagementApi.getAssignments).not.toHaveBeenCalled();
});

it("isolates late page results and exposes a failed batch without retrying per tool", async () => {
  let resolveOld!: (value: TagAssignment[]) => void;
  vi.mocked(tagManagementApi.getToolAssignmentsBatch)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveOld = resolve;
        })
    )
    .mockRejectedValueOnce(new Error("unavailable"));
  const view = renderHook(({ ids }) => useToolTagAssignments(true, ids, 0), {
    initialProps: { ids: ["1"] },
    wrapper: createQueryWrapper(),
  });
  view.rerender({ ids: ["2"] });
  await waitFor(() => expect(view.result.current.isError).toBe(true));
  resolveOld([
    {
      resource_type: "tool",
      resource_id: "1",
      assignment_count: 0,
      assignment_capacity: 100,
      assignments: [],
    },
  ]);
  await waitFor(() => expect(view.result.current.isFetching).toBe(false));
  expect(view.result.current.data).toBeUndefined();
  expect(tagManagementApi.getToolAssignmentsBatch).toHaveBeenCalledTimes(2);
  expect(tagManagementApi.getAssignments).not.toHaveBeenCalled();
});

it("renders supplied batch tags and fallback labels without any row requests", () => {
  render(
    <>
      <ResourceAssignedTags
        resourceType="tool"
        resourceId="1"
        assignments={[
          {
            definition_id: 1,
            definition_key: "team",
            definition_name: "Team",
            selection_mode: "multi_select",
            value_id: 2,
            display_value: "Finance",
            value_status: "active",
          },
        ]}
      />
      <ResourceAssignedTags
        resourceType="tool"
        resourceId="2"
        assignments={[]}
        tags={["Local"]}
      />
    </>
  );
  expect(screen.getByText("Finance")).toBeInTheDocument();
  expect(screen.getByText("Local")).toBeInTheDocument();
  expect(tagManagementApi.getAssignments).not.toHaveBeenCalled();
});
