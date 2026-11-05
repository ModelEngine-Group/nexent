// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { InputField } from "@/components/common/InputField";
import { LoadingIndicator } from "@/components/common/LoadingIndicator";
import { Modal } from "@/components/common/Modal";
import { CreationGuideTour } from "@/components/agent/CreationGuideTour";
import { CsvPreviewTable } from "@/components/preview/CsvPreviewTable";
import { SourceMetadata } from "@/components/chat/sources/SourceMetadata";
import { NoticeHost } from "@/components/providers/NoticeHost";
import { dismissNotice, getNotices, showInfoNotice } from "@/lib/uiNotices";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
afterEach(() => {
  act(() => {
    getNotices().forEach((notice) => dismissNotice(notice.id));
  });
});

it("announces loading through a localized status without exposing the decorative icon", () => {
  render(<LoadingIndicator />);
  expect(
    screen.getByRole("status", { name: "common.loading" })
  ).toHaveTextContent("common.loading");
  expect(screen.getByRole("status").querySelector("svg")).toHaveAttribute(
    "aria-hidden",
    "true"
  );
});

describe("native input compatibility", () => {
  it("clears a controlled field through its regular change handler", async () => {
    const change = vi.fn();
    function Field() {
      const [value, setValue] = useState("draft");
      return (
        <InputField
          aria-label="Name"
          value={value}
          allowClear
          prefix={<span>Prefix</span>}
          onChange={(event) => {
            change(event.target.value);
            setValue(event.target.value);
          }}
        />
      );
    }
    render(<Field />);
    await userEvent.click(screen.getByRole("button", { name: "common.clear" }));
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("");
    expect(change).toHaveBeenCalledExactlyOnceWith("");
    expect(screen.getByRole("textbox")).toHaveFocus();
  });

  it("preserves uncontrolled edits, read-only behavior and composition-aware Enter", async () => {
    const press = vi.fn();
    const view = render(
      <InputField
        aria-label="Search"
        defaultValue="hello"
        allowClear
        onPressEnter={press}
      />
    );
    fireEvent.keyDown(screen.getByRole("textbox"), {
      key: "Enter",
      isComposing: true,
    });
    expect(press).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(press).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "common.clear" }));
    expect(screen.getByRole("textbox")).toHaveValue("");
    view.rerender(
      <InputField aria-label="Search" value="locked" allowClear readOnly />
    );
    expect(
      screen.queryByRole("button", { name: "common.clear" })
    ).not.toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("locked");
  });
});

it("preserves modal drafts across closing and releases its active dialog", async () => {
  const close = vi.fn();
  const view = render(
    <Modal open title="Edit" closeLabel="Close" onClose={close}>
      <input aria-label="Draft" defaultValue="" />
    </Modal>
  );
  await userEvent.type(
    screen.getByRole("textbox", { name: "Draft" }),
    "unsaved"
  );
  await userEvent.keyboard("{Escape}");
  expect(close).toHaveBeenCalledOnce();
  view.rerender(
    <Modal open={false} title="Edit" closeLabel="Close" onClose={close}>
      <input aria-label="Draft" defaultValue="" />
    </Modal>
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  view.rerender(
    <Modal open title="Edit" closeLabel="Close" onClose={close}>
      <input aria-label="Draft" defaultValue="" />
    </Modal>
  );
  expect(screen.getByRole("textbox", { name: "Draft" })).toHaveValue("unsaved");
});

it("retains informational notices after the originating workflow unmounts", async () => {
  function Workflow() {
    const [mounted, setMounted] = useState(true);
    return (
      <>
        <NoticeHost />
        {mounted && (
          <button
            onClick={() => {
              showInfoNotice({
                title: "Access denied",
                content: "No stored copy",
                confirmLabel: "Confirm",
              });
              setMounted(false);
            }}
          >
            Open preview
          </button>
        )}
      </>
    );
  }
  render(<Workflow />);
  await userEvent.click(screen.getByRole("button", { name: "Open preview" }));
  expect(
    screen.queryByRole("button", { name: "Open preview" })
  ).not.toBeInTheDocument();
  expect(screen.getByRole("dialog", { name: "Access denied" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(getNotices()).toHaveLength(0);
});

it("windows a large CSV while preserving rows, columns and scroll callbacks", () => {
  const scroll = vi.fn();
  const rows = Array.from({ length: 10000 }, (_, index) => ({
    _key: String(index),
    value: `Row ${index}`,
  }));
  const columns = [
    { key: "value", dataIndex: "value", title: "Value", width: 160 },
  ];
  const view = render(
    <CsvPreviewTable
      rows={rows}
      columns={columns}
      width={160}
      height={320}
      onScroll={scroll}
    />
  );
  expect(screen.getAllByRole("row").length).toBeLessThan(40);
  expect(screen.getByRole("table")).toHaveAttribute("aria-rowcount", "10001");
  const viewport = screen.getByRole("table").closest("div")!.parentElement!;
  fireEvent.scroll(viewport, { target: { scrollTop: 3200 } });
  expect(scroll).toHaveBeenCalledOnce();
  expect(screen.getByText("Row 100")).toBeInTheDocument();
  expect(screen.queryByText("Row 0")).not.toBeInTheDocument();
  view.rerender(
    <CsvPreviewTable
      rows={rows.slice(0, 2)}
      columns={columns}
      width={160}
      height={320}
    />
  );
  expect(screen.getByText("Row 0")).toBeInTheDocument();
  expect(screen.getByText("Row 1")).toBeInTheDocument();
});

it("keeps metadata pinned while changing between property and JSON tabs", async () => {
  render(
    <SourceMetadata metadata={{ source: "manual", nested: { count: 2 } }} />
  );
  await userEvent.click(
    screen.getByRole("button", { name: "chat.sources.showAttributes" })
  );
  const dialog = await screen.findByRole("dialog");
  await userEvent.click(
    within(dialog).getByRole("tab", { name: "chat.sources.rawJson" })
  );
  expect(within(dialog).getByRole("tabpanel")).toHaveTextContent('"manual"');
  await userEvent.click(
    within(dialog).getByRole("button", { name: "chat.sources.closeAttributes" })
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("advances the real Radix tour and lets the caller persist completion", async () => {
  const finish = vi.fn();
  const close = vi.fn();
  render(
    <CreationGuideTour
      open
      steps={[
        { title: "First step", target: () => null },
        { title: "Last step", target: () => null },
      ]}
      onFinish={finish}
      onClose={close}
    />
  );
  expect(screen.getByRole("dialog", { name: "First step" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "tour.next" }));
  expect(screen.getByRole("dialog", { name: "Last step" })).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "tour.finish" }));
  expect(finish).toHaveBeenCalledOnce();
  expect(close).toHaveBeenCalledExactlyOnceWith(1);
});
