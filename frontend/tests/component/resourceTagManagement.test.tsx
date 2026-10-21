// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { render } from "./resourceDrawerTestUtils";
import ResourceTagAssignmentModal from "@/components/tag/ResourceTagAssignmentModal";
import { tagManagementApi } from "@/services/tagManagementService";
import type { TagAssignment, TagDefinition } from "@/types/tagManagement";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));
vi.mock("@/services/tagManagementService", () => ({
  tagManagementApi: { getAssignments: vi.fn(), replaceAssignments: vi.fn() },
}));

it("saves assignments through the reachable editor and disables readonly tag inputs", async () => {
  const user = userEvent.setup();
  const onSaved = vi.fn();
  const onClose = vi.fn();
  const definition = {
    definition_id: 8,
    definition_key: "department",
    definition_name: "Department",
    selection_mode: "multi_select",
    status: "active",
    values: [{ value_id: 9, display_value: "Finance", status: "active" }],
  } as TagDefinition;
  let assignments: TagAssignment["assignments"] = [];
  vi.mocked(tagManagementApi.getAssignments).mockImplementation(
    async (_, id) => ({
      resource_type: "knowledge_base",
      resource_id: id,
      assignment_count: assignments.length,
      assignment_capacity: 100,
      assignments: id === "kb-index" ? assignments : [],
    })
  );
  vi.mocked(tagManagementApi.replaceAssignments).mockImplementation(
    async () => {
      assignments = [
        {
          definition_id: 8,
          definition_key: "department",
          definition_name: "Department",
          selection_mode: "multi_select",
          value_id: 9,
          display_value: "Finance",
          value_status: "active",
        },
      ];
      return {
        resource_type: "knowledge_base",
        resource_id: "kb-index",
        assignment_count: 1,
        assignment_capacity: 100,
        assignments,
      };
    }
  );
  const view = render(
    <App>
      <ResourceTagAssignmentModal
        open
        resourceType="knowledge_base"
        resourceId="kb-index"
        definitions={[definition]}
        canEdit
        onClose={onClose}
        onSaved={onSaved}
      />
    </App>
  );
  await waitFor(() =>
    expect(
      screen
        .getAllByRole("combobox")
        .some((input) => !input.hasAttribute("disabled"))
    ).toBe(true)
  );
  const input = screen
    .getAllByRole("combobox")
    .filter((element) => !element.hasAttribute("disabled"))
    .at(-1)!;
  await user.click(input);
  await user.click(
    screen.getByText("Finance", { selector: ".ant-select-item-option-content" })
  );
  expect(tagManagementApi.replaceAssignments).not.toHaveBeenCalled();
  await user.click(
    screen.getByRole("button", { name: "tagManagement.action.save" })
  );
  await waitFor(() =>
    expect(tagManagementApi.replaceAssignments).toHaveBeenCalledWith(
      "knowledge_base",
      "kb-index",
      { value_ids: [9] },
      expect.any(Object)
    )
  );
  await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
  expect(onSaved).toHaveBeenCalledWith(
    expect.objectContaining({
      resource_id: "kb-index",
      assignments: [
        expect.objectContaining({ value_id: 9, display_value: "Finance" }),
      ],
    })
  );
  expect(onClose).toHaveBeenCalledOnce();

  view.rerender(
    <App>
      <ResourceTagAssignmentModal
        open
        resourceType="knowledge_base"
        resourceId="readonly"
        definitions={[definition]}
        canEdit={false}
        onClose={onClose}
        onSaved={onSaved}
      />
    </App>
  );
  await waitFor(() =>
    expect(tagManagementApi.getAssignments).toHaveBeenLastCalledWith(
      "knowledge_base",
      "readonly",
      expect.any(Object)
    )
  );
  expect(screen.getByRole("combobox")).toBeDisabled();
  expect(tagManagementApi.replaceAssignments).toHaveBeenCalledOnce();
});
