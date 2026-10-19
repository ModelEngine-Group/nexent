// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { render, screen } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type MockInstance,
} from "vitest";

import AidpResizableTitle from "@/ext_components/aidp/pages/knowledge-list/AidpResizableTitle";
import { AIDP_MIN_COLUMN_WIDTH } from "@/ext_components/aidp/pages/knowledge-list/utils/aidpKnowledgeColumnWidths";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

/** `null` renders the column without a minimum, which is not the same as omitting the argument. */
const renderHeader = (minWidth: number | null = 120) =>
  render(
    <table>
      <thead>
        <tr>
          <AidpResizableTitle
            width={200}
            maxWidth={400}
            minWidth={minWidth ?? undefined}
            data-column-key="name"
            onResize={() => {}}
          >
            名称
          </AidpResizableTitle>
        </tr>
      </thead>
    </table>
  );

describe("AidpResizableTitle", () => {
  let errorSpy: MockInstance<typeof console.error>;

  beforeEach(() => {
    errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    errorSpy.mockRestore();
  });

  it("keeps the resize-only props out of the rendered cell", () => {
    renderHeader();

    const header = screen.getByRole("columnheader");
    // A custom prop that reaches the <th> makes React log
    // "React does not recognize the `minWidth` prop on a DOM element" once per
    // header cell, and writes the attribute into the markup.
    expect(header.hasAttribute("minwidth")).toBe(false);
    expect(header.hasAttribute("maxwidth")).toBe(false);
    expect(header.hasAttribute("onresize")).toBe(false);
    expect(header.getAttribute("data-column-key")).toBe("name");
    expect(header.style.width).toBe("200px");
    const unknownPropWarnings = errorSpy.mock.calls.filter((call: unknown[]) =>
      String(call[0]).includes("does not recognize")
    );
    expect(unknownPropWarnings).toHaveLength(0);
  });

  it("reports the column minimum on the resize handle", () => {
    renderHeader();

    const handle = screen.getByRole("separator");
    expect(handle).toHaveAttribute("aria-valuemin", "120");
    expect(handle).toHaveAttribute("aria-valuemax", "400");
    expect(handle).toHaveAttribute("aria-valuenow", "200");
  });

  it("falls back to the shared minimum when the column has none", () => {
    renderHeader(null);

    expect(screen.getByRole("separator")).toHaveAttribute(
      "aria-valuemin",
      String(AIDP_MIN_COLUMN_WIDTH)
    );
  });
});
