"use client";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { MODEL_TYPES } from "@/const/modelConfig";
import { ModelType } from "@/types/modelConfig";

/**
 * Shared type-display constants for the v2.6.1 model-config redesign.
 *
 * The type-id -> i18n-key map, badge colors, status-dot colors and the
 * localized type-option list are used by the library list, the add/edit
 * dialogs and the batch-manage dialog. Keeping one copy avoids the
 * four-fold duplication across those components.
 */

/** Raw type ids -> the semantic i18n keys used across the app. */
export const TYPE_LABEL_KEY_MAP: Record<string, string> = {
  llm: "llm",
  embedding: "embedding",
  multi_embedding: "multiEmbedding",
  vlm: "imageUnderstanding",
  vlm2: "imageGeneration",
  vlm3: "videoUnderstanding",
  vlm4: "audioUnderstanding",
  rerank: "rerank",
  stt: "stt",
  tts: "tts",
};

export const TYPE_BADGE_CLASS: Record<string, string> = {
  [MODEL_TYPES.LLM]: "bg-blue-100 text-blue-700",
  [MODEL_TYPES.EMBEDDING]: "bg-indigo-100 text-indigo-700",
  [MODEL_TYPES.MULTI_EMBEDDING]: "bg-cyan-100 text-cyan-700",
  [MODEL_TYPES.RERANK]: "bg-purple-100 text-purple-700",
  [MODEL_TYPES.STT]: "bg-orange-100 text-orange-700",
  [MODEL_TYPES.TTS]: "bg-pink-100 text-pink-700",
  [MODEL_TYPES.VLM]: "bg-emerald-100 text-emerald-700",
  [MODEL_TYPES.VLM2]: "bg-emerald-100 text-emerald-700",
  [MODEL_TYPES.VLM3]: "bg-emerald-100 text-emerald-700",
  [MODEL_TYPES.VLM4]: "bg-emerald-100 text-emerald-700",
};

export const STATUS_DOT_CLASS: Record<string, string> = {
  available: "bg-emerald-500",
  unavailable: "bg-red-500",
  detecting: "bg-amber-400 animate-pulse",
  not_detected: "bg-slate-300",
};

export function typeLabel(
  type: string,
  t: (key: string, opts?: any) => string
): string {
  return t(`model.type.${TYPE_LABEL_KEY_MAP[type] ?? type}`, {
    defaultValue: type,
  });
}

/** Localized {value, label} options for every model type, in map order. */
export function useTypeOptions() {
  const { t } = useTranslation();
  return useMemo(
    () =>
      (Object.keys(TYPE_LABEL_KEY_MAP) as ModelType[]).map((v) => ({
        value: v,
        label: t(`model.type.${TYPE_LABEL_KEY_MAP[v] ?? v}`, {
          defaultValue: v,
        }),
      })),
    [t]
  );
}
