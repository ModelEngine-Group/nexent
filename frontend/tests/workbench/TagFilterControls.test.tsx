import { useState } from "react";
import { expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TagFilterControls from "@/components/tag/TagFilterControls";
import type {
  TagDefinition,
  TagDocumentPredicate,
} from "@/types/tagManagement";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const definitions: TagDefinition[] = [
  {
    definition_id: 1,
    bucket_id: 1,
    definition_key: "business",
    definition_name: "Business",
    selection_mode: "multi_select",
    sort_order: 0,
    status: "active",
    active_value_count: 2,
    value_capacity: 10,
    values: [
      {
        value_id: 1,
        display_value: "Finance",
        normalized_value: "finance",
        sort_order: 0,
        status: "active",
      },
      {
        value_id: 2,
        display_value: "Tech",
        normalized_value: "tech",
        sort_order: 1,
        status: "active",
      },
    ],
  },
];

it("tag dropdown stays in its field anchor when selected conditions appear or are removed", async () => {
  const user = userEvent.setup();
  const changed = vi.fn();
  function Harness() {
    const [value, setValue] = useState<TagDocumentPredicate[]>([]);
    return (
      <TagFilterControls
        definitions={definitions}
        value={value}
        onChange={(next) => {
          changed(next);
          setValue(next);
        }}
      />
    );
  }
  render(<Harness />);
  const field = screen
    .getAllByRole("combobox")[1]
    .closest(".ant-select")!.parentElement!;
  await user.click(screen.getAllByRole("combobox")[1]);
  await user.click(
    within(field).getByText("Finance", {
      selector: ".ant-select-item-option-content",
    })
  );
  expect(changed).toHaveBeenLastCalledWith([
    { definition_id: 1, value_ids: [1] },
  ]);
  expect(screen.getByText("Business: Finance")).toBeVisible();
  expect(field.querySelector(".ant-select-dropdown")).not.toBeNull();
  await user.click(
    within(field).getByText("Tech", {
      selector: ".ant-select-item-option-content",
    })
  );
  expect(changed).toHaveBeenLastCalledWith([
    { definition_id: 1, value_ids: [1, 2] },
  ]);
  await user.click(
    screen.getByText("Business: Finance").querySelector(".ant-tag-close-icon")!
  );
  expect(changed).toHaveBeenLastCalledWith([
    { definition_id: 1, value_ids: [2] },
  ]);
  expect(field.querySelector(".ant-select-dropdown")).not.toBeNull();
});
