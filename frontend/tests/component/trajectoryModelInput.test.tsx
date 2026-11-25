// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { TrajectoryNodeDetail } from "@/app/observability/components/TrajectoryNodeDetail";
import { BodyCache } from "@/lib/trajectory";
import { trajectoryService } from "@/services/trajectoryService";
import type { ContentReference } from "@/types/trajectory";
import { body, traceNode } from "./trajectoryFixtures";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { defaultValue?: string; count?: number }) =>
      options?.defaultValue ??
      (options?.count ? `${key}:${options.count}` : key),
  }),
}));
vi.mock("@/services/trajectoryService", () => ({
  trajectoryService: { content: vi.fn() },
}));

function renderInput(input: ContentReference, kind = "model") {
  render(
    <App>
      <TrajectoryNodeDetail
        node={traceNode({ kind, input })}
        conversationId="1"
        cache={new BodyCache()}
        onParent={vi.fn()}
        onLoaded={vi.fn()}
      />
    </App>
  );
  return screen
    .getByRole("button", { name: "trajectory.input" })
    .closest("section")!;
}

it("nests ordered Markdown messages under messages and keeps parameters in the request table", async () => {
  const user = userEvent.setup();
  const request = {
    model: "model-a",
    temperature: 0,
    enable_thinking: false,
    chat_template_kwargs: { enable_thinking: false },
    stop: null,
    messages: [
      { role: "system", content: "### Instructions\n\n1. Use the **facts**" },
      {
        role: "user",
        content: [
          { type: "text", text: "| Item |\n| --- |\n| Pen |" },
          { type: "image_url", image_url: { url: "/private-image" } },
          { type: "text", text: '```json\n{"x":1}\n```' },
        ],
      },
      { role: "assistant", content: null, tool_calls: [{ id: "tool-1" }] },
      { role: "tool", content: "Done | complete", tool_call_id: "tool-1" },
    ],
  };
  const source = JSON.stringify(request);
  const input = renderInput(body(source));
  const table = within(input).getByRole("table", {
    name: "trajectory.modelInput",
  });
  expect(table.closest(".ant-table-wrapper")?.parentElement).toBe(input);
  expect(
    input.querySelector(".trajectory-code-card, .trajectory-body-preview")
  ).toBeNull();
  expect(
    within(input).queryByRole("button", { name: "trajectory.expandContent" })
  ).toBeNull();
  expect(table.querySelector(":scope > thead")).toBeNull();
  const requestRows = Array.from(
    table.querySelectorAll<HTMLTableRowElement>(":scope > tbody > tr")
  );
  expect(
    requestRows.map((row) => row.querySelector(":scope > th")?.textContent)
  ).toEqual([
    "messages",
    "model",
    "temperature",
    "enable_thinking",
    "chat_template_kwargs",
    "stop",
  ]);
  expect(requestRows.every((row) => row.children.length === 2)).toBe(true);
  expect(
    requestRows.slice(1).map((row) => within(row).getByRole("cell").textContent)
  ).toEqual(['"model-a"', "0", "false", '{"enable_thinking":false}', "null"]);
  const messagesTable = within(requestRows[0]).getByRole("table", {
    name: "trajectory.modelInputMessages",
  });
  expect(messagesTable.querySelector(":scope > thead")).toBeNull();
  const rows = Array.from(
    messagesTable.querySelectorAll<HTMLTableRowElement>(":scope > tbody > tr")
  );
  expect(
    rows.map((row) => within(row).getByRole("rowheader").textContent)
  ).toEqual(["system", "user", "assistant", "tool"]);
  expect(rows.every((row) => row.children.length === 2)).toBe(true);
  expect(
    within(rows[0]).getByRole("heading", { name: "Instructions" })
  ).toBeVisible();
  expect(within(rows[0]).getByText("facts").tagName).toBe("STRONG");
  expect(within(rows[1]).getByRole("table")).toHaveTextContent("Pen");
  expect(rows[1].querySelector("pre code")?.textContent).toBe('{"x":1}\n');
  expect(rows[1]).toHaveTextContent("trajectory.modelInputNonText:1");
  expect(rows[2]).toHaveTextContent("trajectory.modelInputToolCalls:1");
  expect(rows[3]).toHaveTextContent("Done | complete");
  expect(table).not.toHaveTextContent("/private-image");
  await user.click(
    within(input.querySelector("header")!).getByRole("button", {
      name: "trajectory.copy",
    })
  );
  expect(await navigator.clipboard.readText()).toBe(source);

  const modes = within(within(input).getByRole("radiogroup"));
  await user.click(modes.getByText("JSON"));
  expect(
    input.querySelector(".trajectory-code-card .trajectory-body-preview")
  ).toBeInTheDocument();
  expect(input.querySelector("pre code")?.textContent).toBe(
    JSON.stringify(request, null, 2)
  );
  await user.click(modes.getByText("trajectory.text"));
  expect(input.querySelector("pre code")?.textContent).toBe(source);
  await user.click(modes.getByText("trajectory.table"));
  expect(
    within(input).getByRole("table", { name: "trajectory.modelInput" })
  ).toBeVisible();
});

it("waits for all chunks before rendering an input table", async () => {
  const source = JSON.stringify({
    messages: [{ role: "user", content: "**Full input**" }],
  });
  const splitAt = 25;
  vi.mocked(trajectoryService.content)
    .mockResolvedValueOnce({
      text: source.slice(0, splitAt),
      offset: 0,
      next_offset: splitAt,
      complete: false,
      offset_unit: "utf8_bytes",
      byte_count: source.length,
      char_count: source.length,
    })
    .mockResolvedValueOnce({
      text: source.slice(splitAt),
      offset: splitAt,
      next_offset: source.length,
      complete: true,
      offset_unit: "utf8_bytes",
      byte_count: source.length,
      char_count: source.length,
    });
  const input = renderInput(body(source.slice(0, splitAt), false));
  await within(input).findByText((_, node) => node?.tagName === "CODE");
  expect(
    within(input).queryByRole("radio", { name: "trajectory.table" })
  ).toBeNull();
  fireEvent.wheel(input.querySelector("pre")!, { deltaY: 10 });
  expect((await within(input).findByText("Full input")).tagName).toBe("STRONG");
});

it.each([
  ["model", '{"messages":[]}'],
  ["model", '{"messages":[{"content":"unknown role"}]}'],
  ["model", '{"messages":[{"role":"user","content":{}}]}'],
  ["model", '{"messages":'],
  [
    "model",
    JSON.stringify({
      messages: [{ role: "user", content: "x".repeat(128 * 1024) }],
    }),
  ],
  [
    "model",
    JSON.stringify({
      messages: [{ role: "user", content: "Input" }],
      ...Object.fromEntries(
        Array.from({ length: 201 }, (_, index) => [`parameter_${index}`, index])
      ),
    }),
  ],
  ["tool", '{"messages":[{"role":"user","content":"same shape"}]}'],
])("keeps the original view for unsupported %s input", (kind, source) => {
  const input = renderInput(body(source), kind);
  expect(within(input).queryByRole("table")).toBeNull();
  expect(
    within(input).queryByRole("radio", { name: "trajectory.table" })
  ).toBeNull();
  expect(input.querySelector("pre code")).toBeVisible();
});

it("does not interpret HTML or fetch Markdown images from an input", () => {
  const input = renderInput(
    body(
      JSON.stringify({
        messages: [
          {
            role: "<tag>",
            content:
              "**Text**\n\n<div id='raw-html'>Hidden</div>\n\n![Image](/markdown.png)",
          },
        ],
      })
    )
  );
  expect(within(input).getByText("Text").tagName).toBe("STRONG");
  expect(within(input).getByText("<tag>")).toBeVisible();
  expect(input.querySelector("#raw-html, img")).toBeNull();
});
