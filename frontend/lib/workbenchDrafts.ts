// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export type WorkbenchComposerDraft = {
  text: string;
  mode: "planning" | "execution";
  owner: string;
};

export const workbenchDraftKey = (identity: string, conversationId?: string) =>
  `workbench:composer:v1:${JSON.stringify([identity, conversationId ?? "new"])}`;

export function readWorkbenchDraft(
  key: string
): WorkbenchComposerDraft | undefined {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) ?? "null");
    if (
      value &&
      typeof value.text === "string" &&
      typeof value.owner === "string" &&
      ["planning", "execution"].includes(value.mode)
    )
      return value;
  } catch {
    /* Storage can be unavailable in private/restricted contexts. */
  }
  return undefined;
}

export function writeWorkbenchDraft(
  key: string,
  draft?: WorkbenchComposerDraft
) {
  try {
    if (draft?.text) sessionStorage.setItem(key, JSON.stringify(draft));
    else sessionStorage.removeItem(key);
  } catch {
    /* Keep the mounted composer usable when storage is unavailable. */
  }
}
