// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export const DEFAULT_AGENT_COLUMN_WIDTHS = {
  name: 240,
  type: 104,
  description: 280,
  status: 104,
  creator: 160,
  updatedAt: 136,
  actions: 232,
};

export type AgentColumnWidths = typeof DEFAULT_AGENT_COLUMN_WIDTHS;
export type AgentColumnKey = keyof AgentColumnWidths;

export const MIN_COLUMN_WIDTHS: AgentColumnWidths = {
  name: 180,
  type: 88,
  description: 180,
  status: 100,
  creator: 120,
  updatedAt: 128,
  actions: 224,
};

export function resizeAgentColumns(
  widths: AgentColumnWidths,
  key: AgentColumnKey,
  width: number
): AgentColumnWidths {
  if (!Number.isFinite(width)) return widths;
  const keys = Object.keys(DEFAULT_AGENT_COLUMN_WIDTHS) as AgentColumnKey[];
  const index = keys.indexOf(key);
  const neighbor = keys[index === keys.length - 1 ? index - 1 : index + 1];
  const nextWidth = Math.round(
    Math.min(4096, Math.max(MIN_COLUMN_WIDTHS[key], width))
  );
  const delta = nextWidth - widths[key];
  return {
    ...widths,
    [key]: nextWidth,
    [neighbor]: Math.max(MIN_COLUMN_WIDTHS[neighbor], widths[neighbor] - delta),
  };
}
