// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { afterEach, expect, it, vi } from "vitest";
import { copyToClipboard } from "@/lib/clipboard";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("falls back to execCommand when Clipboard API writeText rejects", async () => {
  const writeText = vi.fn().mockRejectedValue(new Error("NotAllowedError"));
  vi.stubGlobal("navigator", {
    clipboard: { writeText },
  });

  const execCommand = vi.fn().mockReturnValue(true);
  const appendChild = vi.fn();
  const removeChild = vi.fn();
  const focus = vi.fn();
  const select = vi.fn();
  const textArea = {
    value: "",
    style: {} as Record<string, string>,
    focus,
    select,
  };

  vi.stubGlobal("document", {
    createElement: vi.fn().mockReturnValue(textArea),
    body: { appendChild, removeChild },
    execCommand,
  });

  await copyToClipboard("line one\n\n\nline two\n");

  expect(writeText).toHaveBeenCalledWith("line one\n\nline two");
  expect(execCommand).toHaveBeenCalledWith("copy");
  expect(appendChild).toHaveBeenCalledWith(textArea);
  expect(removeChild).toHaveBeenCalledWith(textArea);
  expect(textArea.value).toBe("line one\n\nline two");
});

it("uses execCommand when Clipboard API is missing", async () => {
  vi.stubGlobal("navigator", {});
  const execCommand = vi.fn().mockReturnValue(true);
  const textArea = {
    value: "",
    style: {} as Record<string, string>,
    focus: vi.fn(),
    select: vi.fn(),
  };
  vi.stubGlobal("document", {
    createElement: vi.fn().mockReturnValue(textArea),
    body: { appendChild: vi.fn(), removeChild: vi.fn() },
    execCommand,
  });

  await copyToClipboard("plain");
  expect(execCommand).toHaveBeenCalledWith("copy");
});
