// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import SkillGroupSelection from "@/components/skill/SkillGroupSelection";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const groups = Array.from({ length: 12 }, (_, index) => ({
  group_id: index + 1,
  group_name: `Group ${index + 1}`,
  group_description: `Description ${index + 1}`,
  user_count: index,
}));

function Selection() {
  const [value, setValue] = useState<number[]>([]);
  return (
    <>
      <output aria-label="Selected IDs">{value.join(",")}</output>
      <SkillGroupSelection groups={groups} value={value} onChange={setValue} />
    </>
  );
}

test("renders actual group descriptions and zero member counts", () => {
  render(<SkillGroupSelection groups={[groups[0]]} />);
  expect(screen.getByText("Group 1")).toBeVisible();
  expect(screen.getByText("Description 1")).toBeVisible();
  expect(screen.getByText("0")).toBeVisible();
  expect(screen.queryByText("Group 11")).not.toBeInTheDocument();
});

test("keeps cross-page selections and limits select-all to the current page", () => {
  render(<Selection />);
  fireEvent.click(screen.getByRole("checkbox", { name: "Group 1" }));
  fireEvent.click(screen.getByTitle("Next Page"));
  fireEvent.click(screen.getByRole("checkbox", { name: "Group 11" }));
  expect(screen.getByLabelText("Selected IDs")).toHaveTextContent("1,11");
  fireEvent.click(screen.getByTitle("Previous Page"));
  expect(screen.getByRole("checkbox", { name: "Group 1" })).toBeChecked();
  fireEvent.click(screen.getAllByRole("checkbox")[0]);
  const ids = screen
    .getByLabelText("Selected IDs")
    .textContent?.split(",")
    .map(Number);
  expect(ids).toHaveLength(11);
  expect(ids).not.toContain(12);
  fireEvent.click(screen.getAllByRole("checkbox")[0]);
  expect(screen.getByLabelText("Selected IDs")).toHaveTextContent(/^11$/);
});

test("prevents selection while saving", () => {
  const change = vi.fn();
  render(
    <SkillGroupSelection groups={[groups[0]]} disabled onChange={change} />
  );
  expect(screen.getByRole("checkbox", { name: "Group 1" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: "Group 1" }));
  expect(change).not.toHaveBeenCalled();
});

test("supports empty and failed loads without fabricating group information", () => {
  const retry = vi.fn();
  const { rerender } = render(<SkillGroupSelection groups={[]} />);
  expect(screen.getByText("skillCreation.noGroups")).toBeVisible();
  rerender(<SkillGroupSelection groups={[]} isError onRetry={retry} />);
  expect(screen.getByText("skillCreation.groupsLoadFailed")).toBeVisible();
  fireEvent.click(
    screen.getByRole("button", { name: "repository.common.retry" })
  );
  expect(retry).toHaveBeenCalledTimes(1);
});
