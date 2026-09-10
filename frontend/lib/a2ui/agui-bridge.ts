/**
 * Bridge module: detect and convert A2UI content between old and AG-UI formats.
 *
 * The backend can emit A2UI content in two formats (during the transition):
 *
 * 1. **Legacy**: raw `<a2ui-json>...</a2ui-json>` blocks embedded in text.
 * 2. **AG-UI**: an `ACTIVITY_SNAPSHOT` JSON object with `activityType: "a2ui-surface"`,
 *    carrying `a2ui_operations` under `content`.
 *
 * This module exposes helpers that both formats share — detection, extraction of
 * the underlying A2UI protocol messages, and conversion into a shape that can be
 * fed to either the existing `A2UIRenderer` (adjacency-list components) or
 * assistant-ui's `JSONGenerativeUI` (`$type` component tree).
 */

export interface A2uiSnapshotRef {
  /** Surface id extracted from the operations. */
  surfaceId: string;
  /** Original AG-UI ACTIVITY_SNAPSHOT payload (kept for rendering). */
  snapshot: Record<string, unknown>;
  /** A2UI protocol messages extracted from the operations (v0.9 / v1.0). */
  messages: A2uiMessage[];
}

export type A2uiMessage =
  | { beginRendering: Record<string, unknown>; version?: string }
  | { surfaceUpdate: Record<string, unknown>; version?: string }
  | { dataModelUpdate: Record<string, unknown>; version?: string }
  | { deleteSurface: Record<string, unknown>; version?: string };

/** Return true when ``content`` parses as an AG-UI ACTIVITY_SNAPSHOT for A2UI. */
export function isAguiActivitySnapshot(content: string): boolean {
  if (!content) return false;
  const trimmed = content.trim();
  if (!trimmed.startsWith("{")) return false;
  try {
    const obj = JSON.parse(trimmed);
    return (
      obj &&
      typeof obj === "object" &&
      obj.type === "ACTIVITY_SNAPSHOT" &&
      obj.activityType === "a2ui-surface" &&
      obj.content &&
      Array.isArray(obj.content.a2ui_operations)
    );
  } catch {
    return false;
  }
}

/** Extract A2UI protocol messages from either legacy or AG-UI content. */
export function extractA2uiMessages(content: string): {
  source: "legacy" | "agui" | null;
  messages: A2uiMessage[];
} {
  if (!content) return { source: null, messages: [] };

  // Try AG-UI format first
  if (isAguiActivitySnapshot(content)) {
    const obj = JSON.parse(content);
    const ops: unknown[] = obj.content?.a2ui_operations ?? [];
    const messages: A2uiMessage[] = [];
    for (const op of ops) {
      if (!op || typeof op !== "object") continue;
      const record = op as Record<string, unknown>;
      if ("createSurface" in record) {
        messages.push({ beginRendering: record.createSurface as Record<string, unknown>, version: record.version as string });
      } else if ("updateComponents" in record) {
        messages.push({ surfaceUpdate: record.updateComponents as Record<string, unknown>, version: record.version as string });
      } else if ("updateSurface" in record) {
        messages.push({ surfaceUpdate: record.updateSurface as Record<string, unknown>, version: record.version as string });
      } else if ("updateDataModel" in record) {
        messages.push({ dataModelUpdate: record.updateDataModel as Record<string, unknown>, version: record.version as string });
      } else if ("deleteSurface" in record) {
        messages.push({ deleteSurface: record.deleteSurface as Record<string, unknown>, version: record.version as string });
      }
    }
    return { source: "agui", messages };
  }

  // Legacy format: handled by existing parser — just return a marker
  return { source: "legacy", messages: [] };
}

/** Convenience wrapper: detect whether any A2UI content is present. */
export function mightContainA2uiAgui(content: string): boolean {
  return isAguiActivitySnapshot(content);
}
