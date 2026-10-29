// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  getConversationModelPreferences,
  patchConversationModelPreferences,
} from "@/services/modelProfileService";

import { withoutModelTokenLimits } from "./modelParameterLayers";

// Unsent choices belong to one local thread, never to browser-wide preferences.
const drafts = new Map<string, Map<number, Record<string, unknown>>>();
const selections = new Map<string, string>();

export function readModelSelectionDraft(scope: string) {
  return selections.get(scope);
}

export function selectModelDraft(scope: string, modelId: string) {
  selections.set(scope, modelId);
}

export function readModelDraft(scope: string, modelId: number) {
  return withoutModelTokenLimits({ ...drafts.get(scope)?.get(modelId) });
}

export function patchModelDraft(
  scope: string,
  modelId: number,
  values: Record<string, unknown>,
  deleted: string[]
) {
  const next = readModelDraft(scope, modelId);
  deleted.forEach((key) => delete next[key]);
  Object.assign(next, values);
  const models = drafts.get(scope) ?? new Map();
  if (Object.keys(next).length) models.set(modelId, next);
  else models.delete(modelId);
  if (models.size) drafts.set(scope, models);
  else drafts.delete(scope);
}

/** Persist existing-conversation drafts before running; failed patches retain intent. */
export async function persistModelDrafts(
  scope: string,
  conversationId?: number
) {
  const snapshot = [...(drafts.get(scope)?.entries() ?? [])].map(
    ([id, values]) => [id, withoutModelTokenLimits(values)] as const
  );
  if (!snapshot.length) return conversationId;
  if (!conversationId) return undefined;
  const id = conversationId;
  for (const [modelId, values] of snapshot) {
    const saved = await getConversationModelPreferences(id, modelId);
    await patchConversationModelPreferences(id, modelId, {
      expected_version: saved.version,
      parameter_values: values,
      delete_parameters: [],
    });
  }
  acknowledgeModelDrafts(scope, Object.fromEntries(snapshot));
  return id;
}

/** Freeze the first-turn intent without creating a conversation of the wrong mode. */
export function snapshotModelDrafts(
  scope: string
): Record<string, Record<string, unknown>> {
  return Object.fromEntries(
    [...(drafts.get(scope)?.entries() ?? [])].map(([id, values]) => [
      String(id),
      structuredClone(values),
    ])
  );
}

/** A response identity confirms persistence; edits made during the request remain drafts. */
export function acknowledgeModelDrafts(
  scope: string,
  sent: Record<string, Record<string, unknown>>
) {
  for (const [id, values] of Object.entries(sent)) {
    const current = readModelDraft(scope, Number(id));
    for (const [key, value] of Object.entries(values)) {
      if (JSON.stringify(current[key]) === JSON.stringify(value))
        delete current[key];
    }
    const models = drafts.get(scope);
    if (Object.keys(current).length) models?.set(Number(id), current);
    else models?.delete(Number(id));
    if (!models?.size) drafts.delete(scope);
  }
}
