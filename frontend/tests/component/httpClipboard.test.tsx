// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import React from "react";
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { copyToClipboard } from "@/lib/clipboard";
import { useClipboardCopy } from "@/hooks/useClipboardCopy";
import { ClipboardFixture, sampleAnswer, sampleCode } from "./clipboardFixture";

function modern(writeText: unknown) {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: writeText ? { writeText } : undefined,
  });
}

beforeEach(() => {
  modern(undefined);
  Object.defineProperty(document, "execCommand", {
    configurable: true,
    value: vi.fn(() => true),
  });
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("HTTP clipboard writer", () => {
  it("copies without Clipboard API and preserves new-chat whitespace", async () => {
    const command = vi.spyOn(document, "execCommand").mockImplementation(() => {
      expect((document.activeElement as HTMLTextAreaElement).value).toBe(
        sampleCode
      );
      return true;
    });
    await copyToClipboard(sampleCode, { preserveWhitespace: true });
    expect(command).toHaveBeenCalledWith("copy");
    expect(document.querySelector("[data-nexent-copy-fallback]")).toBeNull();
  });

  it("retains legacy whitespace normalization by default", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    modern(write);
    await copyToClipboard("\n\nA\n\n\n\nB\n\n");
    expect(write).toHaveBeenCalledWith("A\n\nB");
    expect(document.execCommand).not.toHaveBeenCalled();
  });

  it("prefers modern API with exact requested content", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    modern(write);
    await copyToClipboard(sampleAnswer, { preserveWhitespace: true });
    expect(write).toHaveBeenCalledOnce();
    expect(write).toHaveBeenCalledWith(sampleAnswer);
    expect(document.execCommand).not.toHaveBeenCalled();
  });

  it("falls back after a modern permission rejection", async () => {
    modern(
      vi.fn().mockRejectedValue(new DOMException("denied", "NotAllowedError"))
    );
    await copyToClipboard("fallback");
    expect(document.execCommand).toHaveBeenCalledOnce();
  });

  it.each([false, "throw"])(
    "rejects fallback failure %s without leaving a textarea",
    async (failure) => {
      vi.spyOn(document, "execCommand").mockImplementation(() => {
        if (failure === "throw") throw new Error("blocked");
        return false;
      });
      await expect(copyToClipboard("x")).rejects.toThrow();
      expect(document.querySelector("[data-nexent-copy-fallback]")).toBeNull();
    }
  );

  it("restores input focus, selection, and selection direction", async () => {
    const input = document.createElement("textarea");
    input.value = "original selection";
    document.body.appendChild(input);
    input.focus();
    input.setSelectionRange(2, 7, "backward");
    await copyToClipboard("new");
    expect(document.activeElement).toBe(input);
    expect([
      input.selectionStart,
      input.selectionEnd,
      input.selectionDirection,
    ]).toEqual([2, 7, "backward"]);
    input.remove();
  });

  it("restores a document text selection", async () => {
    const p = document.createElement("p");
    p.textContent = "select this text";
    document.body.appendChild(p);
    const range = document.createRange();
    range.setStart(p.firstChild!, 0);
    range.setEnd(p.firstChild!, 6);
    document.getSelection()!.removeAllRanges();
    document.getSelection()!.addRange(range);
    await copyToClipboard("new");
    expect(document.getSelection()!.toString()).toBe("select");
    p.remove();
  });
});

describe("clipboard feedback lifecycle", () => {
  it("does not show success before write completion and blocks concurrent writes", async () => {
    let finish!: () => void;
    const write = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        })
    );
    modern(write);
    const { result } = renderHook(() => useClipboardCopy({ scopeKey: "one" }));
    let task!: Promise<boolean>;
    act(() => {
      task = result.current.copy("value");
    });
    expect(result.current.isCopied).toBe(false);
    expect(result.current.isCopying).toBe(true);
    await act(async () => {
      expect(await result.current.copy("second")).toBe(false);
    });
    expect(write).toHaveBeenCalledOnce();
    await act(async () => {
      finish();
      await task;
    });
    expect(result.current.isCopied).toBe(true);
  });

  it("reports failure, then allows a successful retry", async () => {
    vi.spyOn(document, "execCommand").mockReturnValue(false);
    const onError = vi.fn(),
      feedback = vi.fn();
    const { result } = renderHook(() =>
      useClipboardCopy({ scopeKey: "one", onError, onCopiedChange: feedback })
    );
    await act(async () => {
      expect(await result.current.copy("x")).toBe(false);
    });
    expect(onError).toHaveBeenCalledOnce();
    expect(feedback).not.toHaveBeenCalledWith(true);
    expect(result.current.isCopied).toBe(false);
    vi.spyOn(document, "execCommand").mockReturnValue(true);
    await act(async () => {
      expect(await result.current.copy("x")).toBe(true);
    });
    expect(feedback).toHaveBeenCalledWith(true);
  });

  it("ignores completion after the message scope changes", async () => {
    let finish!: () => void;
    modern(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        })
    );
    const feedback = vi.fn();
    const { result, rerender } = renderHook(
      ({ scope }) =>
        useClipboardCopy({ scopeKey: scope, onCopiedChange: feedback }),
      { initialProps: { scope: "one" } }
    );
    let task!: Promise<boolean>;
    act(() => {
      task = result.current.copy("x");
    });
    rerender({ scope: "two" });
    await act(async () => {
      finish();
      expect(await task).toBe(false);
    });
    expect(result.current.isCopied).toBe(false);
    expect(feedback).not.toHaveBeenCalledWith(true);
  });

  it("ignores completion after unmount", async () => {
    let finish!: () => void;
    modern(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        })
    );
    const feedback = vi.fn();
    const { result, unmount } = renderHook(() =>
      useClipboardCopy({ scopeKey: "one", onCopiedChange: feedback })
    );
    let task!: Promise<boolean>;
    act(() => {
      task = result.current.copy("x");
    });
    unmount();
    await act(async () => {
      finish();
      expect(await task).toBe(false);
    });
    expect(feedback).not.toHaveBeenCalledWith(true);
  });

  it("restarts the success timer for consecutive copies and cleans it on unmount", async () => {
    vi.useFakeTimers();
    const feedback = vi.fn();
    const { result, unmount } = renderHook(() =>
      useClipboardCopy({ scopeKey: "one", onCopiedChange: feedback })
    );
    await act(async () => {
      await result.current.copy("one");
    });
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    await act(async () => {
      await result.current.copy("two");
    });
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(result.current.isCopied).toBe(true);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current.isCopied).toBe(false);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("ignores empty text", async () => {
    const { result } = renderHook(() => useClipboardCopy({ scopeKey: "one" }));
    await act(async () => {
      expect(await result.current.copy("")).toBe(false);
    });
    expect(document.execCommand).not.toHaveBeenCalled();
  });
});

describe("actual assistant-ui copy integration", () => {
  it("reproduces the original primitive's silent failure without Clipboard API", async () => {
    render(<ClipboardFixture unpatched />);
    fireEvent.click(await screen.findByTestId("answer-copy"));
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByTestId("answer-status")).toHaveTextContent("Ready");
    expect(document.execCommand).not.toHaveBeenCalled();
  });

  it("copies runtime answer text once over HTTP and excludes reasoning", async () => {
    const command = vi.spyOn(document, "execCommand").mockImplementation(() => {
      expect((document.activeElement as HTMLTextAreaElement).value).toBe(
        sampleAnswer
      );
      return true;
    });
    render(<ClipboardFixture />);
    fireEvent.click(await screen.findByTestId("answer-copy"));
    await waitFor(() =>
      expect(screen.getByTestId("answer-status")).toHaveTextContent("Copied")
    );
    expect(command).toHaveBeenCalledOnce();
  });

  it("does not duplicate the primitive's modern API write", async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    modern(write);
    render(<ClipboardFixture />);
    fireEvent.click(await screen.findByTestId("answer-copy"));
    await waitFor(() =>
      expect(screen.getByTestId("answer-status")).toHaveTextContent("Copied")
    );
    expect(write).toHaveBeenCalledOnce();
    expect(write).toHaveBeenCalledWith(sampleAnswer);
  });

  it("keeps the primitive's empty-message disabled state", async () => {
    render(<ClipboardFixture empty />);
    expect(await screen.findByTestId("answer-copy")).toBeDisabled();
  });

  it("shows a failure instead of a success mark", async () => {
    vi.spyOn(document, "execCommand").mockReturnValue(false);
    render(<ClipboardFixture />);
    fireEvent.click(await screen.findByTestId("answer-copy"));
    await waitFor(() =>
      expect(screen.getByTestId("answer-status")).toHaveTextContent(
        "Copy failed"
      )
    );
  });
});
