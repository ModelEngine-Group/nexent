// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import RepositorySearchBar from "@/app/resource-space/components/RepositorySearchBar";

test("uses the same search and filter slots and commits composed text only once", () => {
  const onChange = vi.fn();
  render(
    <RepositorySearchBar
      value=""
      placeholder="Search resources"
      onChange={onChange}
      filter={<button type="button">Tags</button>}
    />
  );

  const search = screen.getByRole("textbox");
  const filter = screen.getByRole("button", { name: "Tags" });
  expect(search.closest(".ant-input-affix-wrapper")).toHaveClass(
    "h-8",
    "w-full"
  );
  expect(filter.parentElement).toHaveClass("sm:max-w-[296px]");

  fireEvent.compositionStart(search);
  fireEvent.change(search, { target: { value: "ji" } });
  expect(search).toHaveValue("ji");
  expect(onChange).not.toHaveBeenCalled();
  fireEvent.change(search, { target: { value: "技能" } });
  fireEvent.compositionEnd(search, { data: "技能" });
  expect(onChange).toHaveBeenCalledExactlyOnceWith("技能");
});
