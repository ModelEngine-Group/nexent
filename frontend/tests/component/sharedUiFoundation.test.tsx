// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { createInstance } from "i18next";
import chineseTranslations from "@/public/locales/zh/common.json";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Button } from "@/components/common/Button";
import { Pagination } from "@/components/common/Pagination";

import translations from "@/public/locales/en/common.json";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) => {
      const label =
        translations.pagination[
          key.replace("pagination.", "") as keyof typeof translations.pagination
        ] ?? key;
      return label.replace(/{{(\w+)}}/g, (_, name: string) =>
        String(values?.[name] ?? "")
      );
    },
  }),
}));

describe("shared UI layers", () => {
  it("resolves shared control labels in both production locales", async () => {
    const i18n = createInstance();
    await i18n.init({
      resources: {
        en: { common: translations },
        zh: { common: chineseTranslations },
      },
      lng: "en",
      fallbackLng: "en",
      ns: ["common"],
      defaultNS: "common",
    });
    for (const language of ["en", "zh"]) {
      await i18n.changeLanguage(language);
      for (const key of [
        "pagination.navigation",
        "pagination.total",
        "pagination.jump",
        "pagination.perPage",
        "tour.previous",
        "tour.next",
        "tour.finish",
        "common.clear",
      ]) {
        const value = i18n.t(key, { count: 20 });
        expect(value).not.toBe(key);
        expect(value).not.toContain("{{");
      }
    }
  });
  it("keeps a basic button from submitting forms and uses semantic variants", async () => {
    const submit = vi.fn((event) => event.preventDefault());
    render(
      <form onSubmit={submit}>
        <Button>Open</Button>
        <Button variant="destructive">Delete</Button>
      </form>
    );
    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Open" })).toHaveClass(
      "bg-primary",
      "hover:bg-primary-hover"
    );
    expect(screen.getByRole("button", { name: "Delete" })).toHaveClass(
      "bg-destructive"
    );
  });

  it("submits once while the caller owns its pending state", async () => {
    const submit = vi.fn();
    function Form() {
      const [loading, setLoading] = useState(false);
      return (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            submit();
            setLoading(true);
          }}
        >
          <Button type="submit" loading={loading}>
            Save
          </Button>
        </form>
      );
    }
    render(<Form />);
    const button = screen.getByRole("button", { name: "Save" });
    await userEvent.dblClick(button);
    expect(submit).toHaveBeenCalledTimes(1);
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
  });

  it("retains compatibility button labels, submit types and disabled links", async () => {
    const click = vi.fn();
    render(
      <>
        <Button variant="default" loading type="submit" size="sm">
          保存
        </Button>
        <Button
          href="/help"
          disabled
          onClick={click}
          variant="outline"
          size="sm"
        >
          Help
        </Button>
      </>
    );
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "保存" })).toHaveAttribute(
      "type",
      "submit"
    );
    await userEvent.click(screen.getByText("Help"));
    expect(click).not.toHaveBeenCalled();
    expect(screen.getByText("Help").closest("a")).not.toHaveAttribute("href");
  });
});

describe("controlled pagination", () => {
  it("requests navigation without changing controlled state or submitting a parent form", async () => {
    const change = vi.fn();
    const submit = vi.fn((event) => event.preventDefault());
    render(
      <form onSubmit={submit}>
        <Pagination
          current={2}
          pageSize={10}
          total={100}
          onPageChange={change}
        />
      </form>
    );
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(change).toHaveBeenCalledExactlyOnceWith(3, 10);
    expect(screen.getByRole("button", { name: "Page 2" })).toHaveAttribute(
      "aria-current",
      "page"
    );
    expect(submit).not.toHaveBeenCalled();
  });

  it("owns the total, size, page and jump controls in one navigation", async () => {
    const change = vi.fn();
    const sizeChange = vi.fn();
    render(
      <Pagination
        current={1}
        pageSize={12}
        total={80}
        showTotal
        showSizeChanger
        showQuickJumper
        pageSizeOptions={[10, 12, 20, 50]}
        onPageChange={change}
        onPageSizeChange={sizeChange}
      />
    );
    const navigation = screen.getByRole("navigation");
    expect(navigation).toHaveTextContent("80 items");
    expect(navigation).toContainElement(screen.getByRole("combobox"));
    expect(navigation).toContainElement(screen.getByTitle("2"));
    const input = screen.getByRole("textbox", { name: "Go to page" });
    await userEvent.type(input, "3");
    await userEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(change).toHaveBeenCalledExactlyOnceWith(3, 12);
    expect(input).toHaveValue("");
    change.mockClear();
    await userEvent.type(input, "bad");
    await userEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(change).not.toHaveBeenCalled();
    await userEvent.type(input, "7");
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "20" } });
    expect(input).toHaveValue("");
    expect(sizeChange).toHaveBeenCalledExactlyOnceWith(20);
    expect(change).toHaveBeenCalledExactlyOnceWith(1, 20);
  });

  it("resets to the first page on page-size change, preserving offered sizes", async () => {
    const change = vi.fn();
    render(
      <Pagination
        current={3}
        pageSize={12}
        total={80}
        showSizeChanger
        pageSizeOptions={[10, 12, 20, 50]}
        onPageChange={change}
      />
    );
    expect(
      screen.getAllByRole("option").map((option) => option.textContent)
    ).toEqual(["10 / page", "12 / page", "20 / page", "50 / page"]);
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Items per page" }),
      "20"
    );
    expect(change).toHaveBeenCalledExactlyOnceWith(1, 20);
  });

  it("disables empty and pending navigation and never emits corrections during rendering", async () => {
    const change = vi.fn();
    const view = render(
      <Pagination current={7} pageSize={10} total={0} onPageChange={change} />
    );
    expect(
      screen
        .getAllByRole("button")
        .every((button) => (button as HTMLButtonElement).disabled)
    ).toBe(true);
    view.rerender(
      <Pagination
        current={2}
        pageSize={10}
        total={100}
        disabled
        showSizeChanger
        showQuickJumper
        onPageChange={change}
      />
    );
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(change).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Go to page" })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "20" } });
    expect(change).not.toHaveBeenCalled();
  });

  it("rejects malformed and out-of-range jumps and accepts a valid jump once", async () => {
    const change = vi.fn();
    const user = userEvent.setup();
    render(
      <Pagination
        current={1}
        pageSize={10}
        total={50}
        showQuickJumper
        onPageChange={change}
      />
    );
    const input = screen.getByRole("textbox", { name: "Go to page" });
    for (const value of ["-1", "2.5", "99"]) {
      await user.type(input, `${value}{Enter}`);
    }
    expect(change).not.toHaveBeenCalled();
    await user.type(input, "3{Enter}");
    await user.tab();
    expect(change).toHaveBeenCalledExactlyOnceWith(3, 10);
  });

  it("keeps large page ranges bounded while the caller controls navigation", async () => {
    function Pages() {
      const [page, setPage] = useState(1);
      return (
        <Pagination
          total={1000000}
          current={page}
          pageSize={10}
          onPageChange={setPage}
        />
      );
    }
    render(<Pages />);
    expect(screen.getAllByRole("button").length).toBeLessThanOrEqual(9);
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByRole("button", { name: "Page 2" })).toHaveAttribute(
      "aria-current",
      "page"
    );
  });
});
