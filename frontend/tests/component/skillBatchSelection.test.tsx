// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { expect, test, vi } from "vitest";
import ResourceCardGrid from "@/components/resource/ResourceCardGrid";
import { RepositoryPresentationContext } from "@/hooks/useRepositoryPresentation";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/hooks/auth/useUserDisplayName", () => ({
  useUserDisplayName: () => (_: unknown, fallback: string) => fallback,
}));
vi.mock("@/components/resource/CreateResourceCard", () => ({
  default: () => null,
}));
vi.mock("@/components/repository/agent/components/AgentCardTags", () => ({
  AgentCardTags: () => null,
}));

function renderManagement(
  remove: (item: { skill_id: number }) => Promise<void>
) {
  const items = [
    { skill_id: 1, name: "Editable skill", permission: "EDIT" },
    { skill_id: 2, name: "Read-only skill", permission: "READ_ONLY" },
  ];
  return render(
    <App>
      <RepositoryPresentationContext.Provider
        value={{ layout: "cards", resourceType: "skill" }}
      >
        <ResourceCardGrid
          items={items}
          showToolbar={false}
          batchDelete={remove}
          canBatchDelete={(item) => item.permission === "EDIT"}
          cardSelectionInHeader
          renderItem={(item, _index, selection) => (
            <div key={item.skill_id}>{selection}</div>
          )}
          renderBatchToolbar={(_controls, state) => (
            <>
              <output aria-label="Selected count">{state.selectedCount}</output>
              {state.selectPageControl}
              <button onClick={state.clearSelection}>Clear selection</button>
              <button
                disabled={!state.selectedCount || state.deleting}
                onClick={state.deleteSelected}
              >
                Delete selected
              </button>
            </>
          )}
        />
      </RepositoryPresentationContext.Provider>
    </App>
  );
}

test("selects editable resources only and clears the management selection", () => {
  const remove = vi.fn().mockResolvedValue(undefined);
  renderManagement(remove);
  expect(
    screen.getByRole("button", { name: "Delete selected" })
  ).toBeDisabled();
  expect(
    screen.getByRole("checkbox", { name: "Read-only skill" })
  ).toBeDisabled();
  fireEvent.click(
    screen.getByRole("checkbox", { name: "resourceCenter.selectPage" })
  );
  expect(screen.getByLabelText("Selected count")).toHaveTextContent("1");
  expect(
    screen.getByRole("checkbox", { name: "Editable skill" })
  ).toBeChecked();
  expect(
    screen.getByRole("checkbox", { name: "Read-only skill" })
  ).not.toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "Clear selection" }));
  expect(screen.getByLabelText("Selected count")).toHaveTextContent("0");
  expect(remove).not.toHaveBeenCalled();
});

test.each([false, true])(
  "confirms deletion and retains failed selection: %s",
  async (fails) => {
    const remove = vi.fn().mockImplementation(async () => {
      if (fails) throw new Error("Deletion failed");
    });
    renderManagement(remove);
    fireEvent.click(screen.getByRole("checkbox", { name: "Editable skill" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete selected" }));
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(
      await screen.findByRole("button", { name: "common.confirm" })
    );
    await waitFor(() => expect(remove).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.getByLabelText("Selected count")).toHaveTextContent(
        fails ? "1" : "0"
      )
    );
    expect(remove.mock.calls[0][0].skill_id).toBe(1);
    if (fails) expect(await screen.findByText("Deletion failed")).toBeVisible();
  }
);
