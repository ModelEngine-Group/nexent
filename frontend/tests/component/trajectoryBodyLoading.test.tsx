// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { App } from "antd";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TrajectoryBody } from "@/app/observability/components/TrajectoryBody";
import { BodyCache } from "@/lib/trajectory";
import { trajectoryService } from "@/services/trajectoryService";
import type { ContentChunk, ContentReference } from "@/types/trajectory";
import { body } from "./trajectoryFixtures";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/services/trajectoryService", () => ({
  trajectoryService: { content: vi.fn() },
}));
const content = vi.mocked(trajectoryService.content);
const chunk = (
  text: string,
  offset: number,
  complete = false
): ContentChunk => ({
  text,
  offset,
  next_offset: offset + new TextEncoder().encode(text).length,
  complete,
  offset_unit: "utf8_bytes",
  byte_count: 12,
  char_count: 4,
});
function mount(
  reference = body("preview", false),
  cache = new BodyCache(),
  onInvalidated = vi.fn()
) {
  const view = render(
    <App>
      <TrajectoryBody
        reference={reference}
        slot="input"
        conversationId="1"
        nodeId="node"
        cache={cache}
        onLoaded={vi.fn()}
        onInvalidated={onInvalidated}
      />
    </App>
  );
  return {
    ...view,
    pre: () => view.container.querySelector("pre")!,
    text: () => view.container.querySelector("pre code")?.textContent,
  };
}
beforeEach(() => content.mockReset());

describe("automatic trajectory body loading", () => {
  it("loads the first chunk and waits for bottom scrolling before appending", async () => {
    content
      .mockResolvedValueOnce(chunk("中文", 0))
      .mockResolvedValueOnce(chunk("后续", 6, true));
    const cache = new BodyCache();
    const view = mount(undefined, cache);
    await waitFor(() =>
      expect(view.text()).toBe(JSON.stringify({ content: "中文" }, null, 2))
    );
    expect(content).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByRole("button", { name: "trajectory.nextChunk" })
    ).not.toBeInTheDocument();
    Object.defineProperties(view.pre(), {
      clientHeight: { configurable: true, value: 100 },
      scrollHeight: { configurable: true, value: 300 },
    });
    fireEvent.scroll(view.pre(), { target: { scrollTop: 50 } });
    expect(content).toHaveBeenCalledTimes(1);
    fireEvent.scroll(view.pre(), { target: { scrollTop: 200 } });
    await waitFor(() =>
      expect(view.text()).toBe(JSON.stringify({ content: "中文后续" }, null, 2))
    );
    expect(content.mock.calls.map((call) => call[2])).toEqual([0, 6]);
    expect(cache.matches("node:", "文后")).toBe(true);
    fireEvent.scroll(view.pre(), { target: { scrollTop: 220 } });
    expect(content).toHaveBeenCalledTimes(2);
  });

  it("uses downward wheel input for content shorter than the viewport and deduplicates pending reads", async () => {
    let resolve!: (value: ContentChunk) => void;
    content.mockResolvedValueOnce(chunk("中文", 0)).mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    const view = mount();
    await waitFor(() => expect(view.text()).toContain("中文"));
    fireEvent.wheel(view.pre(), { deltaY: -10 });
    expect(content).toHaveBeenCalledTimes(1);
    fireEvent.wheel(view.pre(), { deltaY: 10 });
    fireEvent.wheel(view.pre(), { deltaY: 10 });
    expect(content).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("status")).toHaveTextContent(
      "trajectory.loadingContent"
    );
    await act(async () => resolve(chunk("后续", 6, true)));
    expect(view.text()).toContain("中文后续");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("retries the failed offset without duplicating preceding text", async () => {
    content
      .mockResolvedValueOnce(chunk("中文", 0))
      .mockRejectedValueOnce({ code: "storage_unavailable" })
      .mockResolvedValueOnce(chunk("后续", 6, true));
    const view = mount();
    await waitFor(() => expect(view.text()).toContain("中文"));
    fireEvent.wheel(view.pre(), { deltaY: 1 });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "trajectory.errors.storage_unavailable"
    );
    fireEvent.wheel(view.pre(), { deltaY: 1 });
    expect(content).toHaveBeenCalledTimes(2);
    await userEvent.click(
      screen.getByRole("button", { name: "trajectory.retry" })
    );
    await waitFor(() => expect(view.text()).toContain("中文后续"));
    expect(content.mock.calls.map((call) => call[2])).toEqual([0, 6, 6]);
    expect(view.text()).not.toContain("中文中文");
  });

  it("retries a failed first chunk at zero", async () => {
    content
      .mockRejectedValueOnce({ code: "storage_unavailable" })
      .mockResolvedValueOnce(chunk("中文", 0, true));
    const view = mount();
    await screen.findByRole("alert");
    await userEvent.click(
      screen.getByRole("button", { name: "trajectory.retry" })
    );
    await waitFor(() => expect(view.text()).toContain("中文"));
    expect(content.mock.calls.map((call) => call[2])).toEqual([0, 0]);
  });

  it.each([
    body("complete", true),
    { ...body("missing", false), availability: "not_returned" },
    { ...body("no reference", false), content_id: null },
  ] satisfies ContentReference[])(
    "does not fetch complete or unavailable content: %s",
    (reference) => {
      mount(reference);
      expect(content).not.toHaveBeenCalled();
    }
  );

  it("invalidates the viewer and cache when an automatic request loses authorization", async () => {
    const cache = new BodyCache();
    cache.set("private", "private content");
    const error = { code: "invalid_reference" };
    const invalidated = vi.fn();
    content.mockRejectedValueOnce(error);
    mount(undefined, cache, invalidated);
    await waitFor(() => expect(invalidated).toHaveBeenCalledWith(error));
    expect(cache.bytes).toBe(0);
    expect(content).toHaveBeenCalledTimes(1);
  });

  it("rejects a non-advancing offset instead of repeating requests", async () => {
    content.mockResolvedValueOnce({ ...chunk("", 0), next_offset: 0 });
    const view = mount();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "trajectory.errors.invalid_parameters"
    );
    fireEvent.wheel(view.pre(), { deltaY: 1 });
    expect(content).toHaveBeenCalledTimes(1);
  });

  it("keeps the accepted prefix and stops when the body reaches its byte budget", async () => {
    content
      .mockResolvedValueOnce(chunk("中文", 0))
      .mockResolvedValueOnce(chunk("后续", 6, true));
    const view = mount(undefined, new BodyCache(6));
    await waitFor(() => expect(view.text()).toContain("中文"));
    fireEvent.wheel(view.pre(), { deltaY: 1 });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "trajectory.errors.body_budget_exceeded"
    );
    expect(view.text()).toContain("中文");
    expect(view.text()).not.toContain("后续");
    expect(content).toHaveBeenCalledTimes(2);
  });

  it("discards a late result after unmounting", async () => {
    let resolve!: (value: ContentChunk) => void;
    content.mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    const cache = new BodyCache();
    const view = mount(undefined, cache);
    const signal = content.mock.calls[0][3]!;
    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => resolve(chunk("late", 0, true)));
    expect(cache.bytes).toBe(0);
  });

  it("aborts the previous node and resets the content when selection changes", async () => {
    let resolve!: (value: ContentChunk) => void;
    content
      .mockImplementationOnce(
        () =>
          new Promise((done) => {
            resolve = done;
          })
      )
      .mockResolvedValueOnce(chunk("新节点", 0, true));
    const cache = new BodyCache();
    const props = {
      reference: body("preview", false),
      slot: "input",
      conversationId: "1",
      cache,
      onLoaded: vi.fn(),
    };
    const view = render(
      <App>
        <TrajectoryBody {...props} nodeId="old" />
      </App>
    );
    const signal = content.mock.calls[0][3]!;
    view.rerender(
      <App>
        <TrajectoryBody {...props} nodeId="new" />
      </App>
    );
    expect(signal.aborted).toBe(true);
    await waitFor(() =>
      expect(view.container.querySelector("pre code")?.textContent).toContain(
        "新节点"
      )
    );
    await act(async () => resolve(chunk("旧节点", 0, true)));
    expect(view.container.querySelector("pre code")?.textContent).not.toContain(
      "旧节点"
    );
    expect(cache.get("old:input:0")).toBeUndefined();
    expect(content.mock.calls.map((call) => call[2])).toEqual([0, 0]);
  });
});
