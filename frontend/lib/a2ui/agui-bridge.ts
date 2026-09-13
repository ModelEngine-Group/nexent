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

/**
 * Convert AG-UI flat component format → Nexus nested format.
 *
 * AG-UI flat (after backend _flatten_and_collect):
 *   { id: "chart", component: "Chart", props: { chartType: "bar", ... }, children: ["childId"] }
 *
 * Nexus nested (what legacy A2UIRenderer expects):
 *   { id: "chart", component: { type: "Chart", props: { chartType: "bar", ... } } }
 *
 * Also restores `props.child` / `props.children` from the top-level `children` array.
 */
function flattenToNexusComponents(
  flatComponents: unknown[]
): unknown[] {
  if (!Array.isArray(flatComponents)) return flatComponents;
  return flatComponents.map((raw) => {
    if (!raw || typeof raw !== "object") return raw;
    const comp = raw as Record<string, unknown>;

    // Already Nexus nested — leave alone
    if (
      comp.component &&
      typeof comp.component === "object" &&
      !Array.isArray(comp.component)
    ) {
      const inner = comp.component as Record<string, unknown>;
      if (typeof inner.type === "string") return raw;
    }

    const componentName = comp.component;
    if (typeof componentName !== "string") return raw;

    const flatProps =
      comp.props && typeof comp.props === "object"
        ? ({ ...(comp.props as Record<string, unknown>) } as Record<string, unknown>)
        : ({} as Record<string, unknown>);

    // Restore child references from top-level children array
    const topChildren = Array.isArray(comp.children)
      ? (comp.children as unknown[])
      : [];
    if (topChildren.length > 0) {
      if (topChildren.length === 1) {
        flatProps.child = topChildren[0];
      } else {
        flatProps.children = { explicitList: topChildren };
      }
    }

    return {
      id: comp.id,
      component: {
        type: componentName,
        props: flatProps,
      },
    };
  });
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
        const uc = record.updateComponents as Record<string, unknown>;
        const components = Array.isArray(uc.components)
          ? flattenToNexusComponents(uc.components)
          : uc.components;
        messages.push({ surfaceUpdate: { ...uc, components }, version: record.version as string });
      } else if ("updateSurface" in record) {
        const us = record.updateSurface as Record<string, unknown>;
        const components = Array.isArray(us.components)
          ? flattenToNexusComponents(us.components)
          : us.components;
        messages.push({ surfaceUpdate: { ...us, components }, version: record.version as string });
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

/**
 * Convert Nexus nested A2UI messages (beginRendering / surfaceUpdate /
 * dataModelUpdate / deleteSurface) into an AG-UI ACTIVITY_SNAPSHOT payload.
 * This lets legacy `<a2ui-json>` tagged content share the same
 * A2uiBridgeSurface → preprocessOperations → convertSurfaceToUISpec →
 * renderGenerativeUI pipeline as AG-UI content.
 *
 * The only transformation performed on the component tree is flattening:
 * Nexus `{component: {type, props}}` → AG-UI `{component: type, props, children}`.
 */
export function nexusMessagesToAguiSnapshot(
  messages: A2uiMessage[]
): Record<string, unknown> {
  const ops: Record<string, unknown>[] = [];

  for (const raw of messages) {
    if (!raw || typeof raw !== "object") continue;
    const msg = raw as Record<string, unknown>;
    const version = String(msg.version ?? "v0.9");

    if (msg.beginRendering) {
      ops.push({ version, createSurface: msg.beginRendering });
    } else if (msg.surfaceUpdate) {
      const su = msg.surfaceUpdate as Record<string, unknown>;
      // Nexus nested → AG-UI flat
      const components = (
        Array.isArray(su.components) ? su.components : []
      ).map((c: Record<string, unknown>) => {
        if (!c || typeof c !== "object") return c;
        const inner = c.component;
        // Already AG-UI flat — leave alone
        if (typeof inner === "string") return c;
        if (!inner || typeof inner !== "object") return c;

        const innerObj = inner as Record<string, unknown>;
        const flatProps = {
          ...((innerObj.props as Record<string, unknown>) ?? {}),
        };
        // Restore children references
        const topChildren: unknown[] = [];
        if (flatProps.child !== undefined) {
          topChildren.push(flatProps.child);
          delete flatProps.child;
        }
        const innerChildren = flatProps.children;
        if (Array.isArray(innerChildren)) {
          topChildren.push(...innerChildren);
          delete flatProps.children;
        } else if (
          innerChildren &&
          typeof innerChildren === "object" &&
          Array.isArray(
            (innerChildren as Record<string, unknown>).explicitList
          )
        ) {
          topChildren.push(
            ...((innerChildren as Record<string, unknown>)
              .explicitList as unknown[])
          );
          delete flatProps.children;
        }
        return {
          id: c.id,
          component: innerObj.type,
          props: flatProps,
          children: topChildren,
        };
      });
      ops.push({
        version,
        updateComponents: { surfaceId: su.surfaceId, components },
      });
    } else if (msg.dataModelUpdate) {
      ops.push({ version, updateDataModel: msg.dataModelUpdate });
    } else if (msg.deleteSurface) {
      ops.push({ version, deleteSurface: msg.deleteSurface });
    }
  }

  return {
    type: "ACTIVITY_SNAPSHOT",
    messageId: `legacy-${Date.now()}`,
    activityType: "a2ui-surface",
    replace: true,
    content: { a2ui_operations: ops },
  };
}
