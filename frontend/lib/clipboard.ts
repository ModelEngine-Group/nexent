// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export interface ClipboardCopyOptions {
  preserveWhitespace?: boolean;
}

export async function copyToClipboard(
  text: string,
  { preserveWhitespace = false }: ClipboardCopyOptions = {}
): Promise<void> {
  const value = preserveWhitespace
    ? text
    : text.replace(/^\n+|\n+$/g, "").replace(/\n{3,}/g, "\n\n");
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      // Permission failures also get the existing user-gesture fallback.
    }
  }
  if (typeof document === "undefined") {
    throw new Error("Clipboard copying requires a document");
  }
  const active = document.activeElement;
  const selection = document.getSelection();
  const ranges = selection
    ? Array.from({ length: selection.rangeCount }, (_, index) =>
        selection.getRangeAt(index).cloneRange()
      )
    : [];
  const input =
    active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement
      ? active
      : null;
  const inputSelection = input
    ? ([
        input.selectionStart,
        input.selectionEnd,
        input.selectionDirection,
      ] as const)
    : null;
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.readOnly = true;
  textarea.setAttribute("aria-hidden", "true");
  textarea.setAttribute("data-nexent-copy-fallback", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  try {
    document.body.appendChild(textarea);
    textarea.focus({ preventScroll: true });
    textarea.select();
    if (!document.execCommand("copy")) {
      throw new Error("Clipboard copy fallback failed");
    }
  } finally {
    textarea.remove();
    // Restoring UI state must not turn a successful copy into an error.
    try {
      if (active instanceof HTMLElement && active.isConnected) {
        active.focus({ preventScroll: true });
      }
      if (input && inputSelection && inputSelection[0] !== null) {
        input.setSelectionRange(
          inputSelection[0],
          inputSelection[1],
          inputSelection[2] ?? undefined
        );
      } else if (selection) {
        selection.removeAllRanges();
        ranges.forEach((range) => selection.addRange(range));
      }
    } catch {
      // The previous selection may have been removed by a concurrent render.
    }
  }
}
