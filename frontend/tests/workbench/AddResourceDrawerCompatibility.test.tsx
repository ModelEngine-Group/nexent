// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import {
  AddResourceDrawer,
  type AddResourceDrawerProps,
} from "@/components/resource-picker/AddResourceDrawer";

vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

function drawer(overrides: Partial<AddResourceDrawerProps> = {}) {
  return (
    <AddResourceDrawer
      open
      title="Fixture resources"
      searchPlaceholder="Search resources"
      selected={[]}
      listTitle="Results"
      total={0}
      onClose={vi.fn()}
      {...overrides}
    >
      <div>Resource list</div>
    </AddResourceDrawer>
  );
}

it("preserves workbench sizing, footer, custom pagination and disabled confirmation", () => {
  const confirm = vi.fn();
  render(
    drawer({
      size: "min(760px, 100vw)",
      width: 560,
      bodyClassName: "fixture-body",
      contentClassName: "fixture-list",
      showPagination: false,
      confirmText: "Select resources",
      closeText: "Cancel resources",
      confirmDisabled: true,
      onConfirm: confirm,
      footerLeading: <button>Retrieval settings</button>,
      paginationContent: <nav>Fixed pagination</nav>,
    })
  );
  expect(
    document.querySelector(".ant-drawer-section")?.parentElement
  ).toHaveStyle({ width: "min(760px, 100vw)" });
  expect(document.querySelector(".ant-drawer-body")).toHaveClass(
    "fixture-body"
  );
  expect(
    document.querySelector('[data-picker-part="list-content"]')
  ).toHaveClass("fixture-list", "flex-1", "overflow-y-auto");
  expect(screen.getByRole("navigation")).toHaveTextContent("Fixed pagination");
  expect(
    document.querySelector('[data-picker-part="footer"]')
  ).toContainElement(
    screen.getByRole("button", { name: "Retrieval settings" })
  );
  fireEvent.click(screen.getByRole("button", { name: "Select resources" }));
  expect(confirm).not.toHaveBeenCalled();
  expect(
    screen.getByRole("button", { name: "Select resources" })
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Cancel resources" })
  ).toBeEnabled();
});

it("retains the develop width fallback and blocks every close path while confirming", () => {
  const close = vi.fn(),
    confirm = vi.fn();
  const view = render(
    drawer({
      width: 560,
      onClose: close,
      onConfirm: confirm,
      confirmLoading: true,
    })
  );
  expect(
    document.querySelector(".ant-drawer-section")?.parentElement
  ).toHaveStyle({ width: "560px" });
  const cancel = within(
    document.querySelector('[data-picker-part="footer"]') as HTMLElement
  ).getByRole("button", { name: "关闭" });
  const submit = screen.getByRole("button", { name: "确认" });
  expect(cancel).toBeDisabled();
  expect(submit).toBeDisabled();
  expect(submit).toHaveAttribute("aria-busy", "true");
  expect(submit.querySelector("svg")).toHaveClass("animate-spin");
  for (const button of screen.getAllByRole("button", {
    name: "关闭",
  }))
    fireEvent.click(button);
  fireEvent.click(submit);
  expect(close).not.toHaveBeenCalled();
  expect(confirm).not.toHaveBeenCalled();
  view.rerender(drawer({ width: 560, onClose: close, onConfirm: confirm }));
  fireEvent.click(screen.getAllByRole("button", { name: "关闭" })[0]);
  expect(close).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "确认" }));
  expect(confirm).toHaveBeenCalledOnce();
});
