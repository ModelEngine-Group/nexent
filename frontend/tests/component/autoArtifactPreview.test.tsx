// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook } from "@testing-library/react";
import { expect, test } from "vitest";
import { useAutoArtifactPreview } from "@/app/newchat/components/use-auto-artifact-preview";
import type { ConversationArtifact } from "@/app/newchat/utils/conversation-artifacts";

const file = (
  name: string,
  key = name,
  objectName = `workspace/${name}`
): ConversationArtifact => ({
  key,
  messageId: "assistant",
  attachment: {
    id: key,
    name,
    object_name: objectName,
  } as ConversationArtifact["attachment"],
});
const initial = {
  scopeKey: "chat-1",
  artifacts: [] as ConversationArtifact[],
  isRunning: false,
  isLoading: false,
  enabled: true,
};

test("opens a new document only after the live run finishes", () => {
  const { result, rerender } = renderHook(useAutoArtifactPreview, {
    initialProps: initial,
  });
  rerender({ ...initial, isRunning: true });
  const doc = file("report.docx");
  rerender({ ...initial, isRunning: true, artifacts: [doc] });
  expect(result.current.selected).toBeNull();
  rerender({ ...initial, artifacts: [doc] });
  expect(result.current.selected).toEqual(doc);
});

test("history loading and conversation switching never auto-open old documents", () => {
  const old = file("old.docx");
  const { result, rerender } = renderHook(useAutoArtifactPreview, {
    initialProps: { ...initial, isLoading: true },
  });
  rerender({ ...initial, artifacts: [old] });
  expect(result.current.selected).toBeNull();
  act(() => result.current.open(old));
  expect(result.current.selected).toEqual(old);
  rerender({
    ...initial,
    scopeKey: "chat-2",
    artifacts: [file("another.pdf")],
  });
  expect(result.current.selected).toBeNull();
  rerender({ ...initial, artifacts: [old] });
  expect(result.current.selected).toBeNull();
});

test("prefers Office originals over companion PDF checks and intermediate scripts", () => {
  const { result, rerender } = renderHook(useAutoArtifactPreview, {
    initialProps: initial,
  });
  rerender({ ...initial, isRunning: true });
  const doc = file("report.docx");
  rerender({
    ...initial,
    isRunning: true,
    artifacts: [doc, file("report.pdf"), file("build.py")],
  });
  rerender({
    ...initial,
    artifacts: [doc, file("report.pdf"), file("build.py")],
  });
  expect(result.current.selected).toEqual(doc);
});

test("closing suppresses late files and metadata updates until another run", () => {
  const { result, rerender } = renderHook(useAutoArtifactPreview, {
    initialProps: initial,
  });
  const doc = file("report.docx");
  rerender({ ...initial, isRunning: true, artifacts: [doc] });
  rerender({ ...initial, artifacts: [doc] });
  act(() => result.current.close());
  const renamed = file("report.docx", "restored-id");
  rerender({ ...initial, artifacts: [renamed, file("late.pdf")] });
  expect(result.current.selected).toBeNull();
  act(() => result.current.open(renamed));
  expect(result.current.selected).toEqual(renamed);
  act(() => result.current.close());
  rerender({ ...initial, isRunning: true, artifacts: [renamed] });
  const next = file("new.docx");
  rerender({ ...initial, artifacts: [renamed, next] });
  expect(result.current.selected).toEqual(next);
});

test("supports late artifact publication after completion without repeating on token updates", () => {
  const { result, rerender } = renderHook(useAutoArtifactPreview, {
    initialProps: initial,
  });
  rerender({ ...initial, isRunning: true });
  rerender(initial);
  const doc = file("published.pdf");
  rerender({ ...initial, artifacts: [doc] });
  expect(result.current.selected).toEqual(doc);
  act(() => result.current.close());
  rerender({ ...initial, artifacts: [{ ...doc }] });
  expect(result.current.selected).toBeNull();
});

test("a late companion PDF does not replace the Office original", () => {
  const { result, rerender } = renderHook(useAutoArtifactPreview, {
    initialProps: initial,
  });
  const doc = file("report.docx");
  rerender({ ...initial, isRunning: true, artifacts: [doc] });
  rerender({ ...initial, artifacts: [doc] });
  rerender({ ...initial, artifacts: [doc, file("report.pdf")] });
  expect(result.current.selected).toEqual(doc);
});

test.each(["build.js", "build.py", "archive.zip", "image.png"])(
  "does not auto-open intermediate or unsupported %s",
  (name) => {
    const { result, rerender } = renderHook(useAutoArtifactPreview, {
      initialProps: initial,
    });
    rerender({ ...initial, isRunning: true });
    rerender({ ...initial, artifacts: [file(name)] });
    expect(result.current.selected).toBeNull();
  }
);

test("does not auto-open missing sources or read-only views", () => {
  const { result, rerender } = renderHook(useAutoArtifactPreview, {
    initialProps: { ...initial, enabled: false },
  });
  rerender({ ...initial, enabled: false, isRunning: true });
  rerender({ ...initial, enabled: false, artifacts: [file("report.docx")] });
  expect(result.current.selected).toBeNull();
  rerender({ ...initial, isRunning: true });
  rerender({ ...initial, artifacts: [file("missing.docx", "missing", "")] });
  expect(result.current.selected).toBeNull();
});

test("reloading the same conversation resets generation observation", () => {
  const { result, rerender } = renderHook(useAutoArtifactPreview, {
    initialProps: initial,
  });
  rerender({ ...initial, isRunning: true });
  rerender({ ...initial, isLoading: true });
  rerender({ ...initial, artifacts: [file("history.docx")] });
  expect(result.current.selected).toBeNull();
});

test("waits for a real preview source when a file marker arrives before upload", () => {
  const { result, rerender } = renderHook(useAutoArtifactPreview, {
    initialProps: initial,
  });
  rerender({ ...initial, isRunning: true });
  const pending = file("report.docx", "pending", "");
  rerender({ ...initial, isRunning: true, artifacts: [pending] });
  rerender({ ...initial, artifacts: [pending] });
  expect(result.current.selected).toBeNull();
  const uploaded = {
    ...pending,
    attachment: {
      ...pending.attachment,
      preview_url: "https://files/report.docx",
    },
  } as ConversationArtifact;
  rerender({ ...initial, artifacts: [uploaded] });
  expect(result.current.selected).toEqual(uploaded);
});
