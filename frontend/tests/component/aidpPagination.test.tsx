// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import AidpPagination from "@/ext_components/aidp/shared/components/AidpPagination";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    i18n: { language: "en" },
    t: (key: string, options?: { size: number }) =>
      key === "aidpKnowledge.pageSizeOption" ? `${options?.size} items` : key,
  }),
}));

it("uses catalog options and keeps controlled pagination callbacks", () => {
  const page = vi.fn();
  const size = vi.fn();
  render(
    <AidpPagination
      currentPage={2}
      pageSize={12}
      total={60}
      totalReliable
      hasMore
      onPageChange={page}
      onPageSizeChange={size}
      pageSizeOptions={[12, 24, 48]}
    />
  );
  fireEvent.mouseDown(
    screen.getByRole("combobox", { name: "aidpKnowledge.pageSize" })
  );
  expect(screen.getByText("24 items")).toBeInTheDocument();
  expect(screen.getByText("48 items")).toBeInTheDocument();
  expect(screen.queryByText("10 items")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("24 items"));
  expect(size).toHaveBeenCalledTimes(1);
  expect(size.mock.calls[0][0]).toBe(24);
  expect(page).not.toHaveBeenCalled();
});

it("retains shared defaults and a nonstandard current size without an override", () => {
  render(
    <AidpPagination
      currentPage={1}
      pageSize={30}
      total={90}
      totalReliable
      hasMore
      onPageChange={vi.fn()}
      onPageSizeChange={vi.fn()}
    />
  );
  fireEvent.mouseDown(
    screen.getByRole("combobox", { name: "aidpKnowledge.pageSize" })
  );
  for (const size of [10, 20, 30, 50, 100]) {
    expect(screen.getAllByText(`${size} items`).length).toBeGreaterThan(0);
  }
  expect(screen.queryByText("12 items")).not.toBeInTheDocument();
});
