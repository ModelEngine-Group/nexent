/**
 * A2UI over AG-UI bridge — generative-ui renderer + A2UI surface state management.
 *
 * This module provides the **client-side bridge** between AG-UI ACTIVITY_SNAPSHOT
 * events (emitted by the backend as ``ProcessType.A2UI`` SSE chunks) and
 * assistant-ui's native generative UI rendering pipeline.
 *
 * Architecture:
 *   Backend SSE (ACTIVITY_SNAPSHOT)
 *     → mapChunkType("a2ui") → "text"
 *     → messageTransformer.ts detects isAguiActivitySnapshot
 *     → A2uiBridgeSurface receives operations
 *     → applyA2uiOperations (reducer) → per-surface state
 *     → convertSurfaceToUISpec (official converter) → { $type, ...props } spec tree
 *     → renderGenerativeUI (or legacy A2UIRenderer fallback) → React nodes
 *
 * Custom A2UI components (Chart, ChoicePicker, Slider, DateTimeInput, List, Tabs)
 * that are **not** in convertSurfaceToUISpec's hardcoded SUPPORTED_COMPONENTS set
 * will appear as warnings. When warnings contain unknown components, the bridge
 * automatically falls back to the legacy ``A2UIRenderer`` for that surface.
 *
 * Action channel: Button clicks currently route through the existing
 * ``setGlobalA2UIActionHandler`` (which posts the action as a text query
 * to the backend for a new run). The AG-UI ``$action`` → ``useAgUiSendA2uiAction``
 * path is gated on a future runtime migration (see Layer 4 of the migration plan).
 */

"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  applyA2uiOperations,
  convertSurfaceToUISpec,
  type A2uiOperation,
  type A2uiState,
  type A2uiSurfaceState,
  type A2uiOperationResult,
} from "@assistant-ui/react-generative-ui/a2ui";
import {
  defaultGenerativeUILibrary,
  renderGenerativeUI,
} from "@assistant-ui/react-generative-ui";

// ---------------------------------------------------------------------------
// Custom component preprocessor — maps A2UI components outside
// convertSurfaceToUISpec's SUPPORTED_COMPONENTS set into compositions of
// standard components (Text / Card / Column / Row / Button / TextField /
// CheckBox / Divider / Image).  Runs on each operation's components array
// **before** applyA2uiOperations, so the reducer + converter never see
// unknown component names and produce zero warnings.
// ---------------------------------------------------------------------------

const SUPPORTED_COMPONENTS = new Set([
  "Text",
  "Image",
  "Row",
  "Column",
  "Card",
  "Divider",
  "Button",
  "TextField",
  "CheckBox",
]);

/** Mapping for components that have a direct 1:1 equivalent in the generative-ui library. */
const DIRECT_COMPONENT_MAP: Record<string, string> = {
  /** A2UI Container is functionally the same as Column. */
  Container: "Column",
};

/**
 * Apply preprocessing to a single component node.
 * Returns either the original node (if already supported), or a replacement
 * composed entirely from supported components (potentially with new children).
 */
function preprocessComponent(
  node: Record<string, unknown>,
  nextId: () => string
): Record<string, unknown> {
  const component = String(node.component ?? "");

  // Already supported — recurse into children, leave alone
  if (SUPPORTED_COMPONENTS.has(component)) {
    return node;
  }

  // Direct mapping
  if (DIRECT_COMPONENT_MAP[component]) {
    return { ...node, component: DIRECT_COMPONENT_MAP[component] };
  }

  // ---- Custom transformations ----
  switch (component) {
    case "Heading": {
      // Heading → Text with bold/title semantics.
      const level = Number((node.level as number) ?? 2);
      const text = String((node.text as string) ?? "");
      const prefix = level === 1 ? "# " : level === 2 ? "## " : "### ";
      return {
        ...node,
        component: "Text",
        text: `${prefix}${text}`,
      };
    }

    case "Badge": {
      // Badge → inline Text with color label.
      const label = String((node.label as string) ?? "");
      const color = String((node.color as string) ?? "gray");
      return {
        ...node,
        component: "Text",
        text: `【${label}】`,
      };
    }

    case "Code": {
      // Code → Text (markdown code block via triple backticks).
      const code = String((node.code as string) ?? (node.text as string) ?? "");
      const lang = String((node.language as string) ?? "");
      return {
        ...node,
        component: "Text",
        text: `\n\`\`\`${lang}\n${code}\n\`\`\`\n`,
      };
    }

    case "DateTimeInput": {
      // DateTimeInput → TextField with a date-oriented label.
      const label = String((node.label as string) ?? "选择日期");
      return {
        ...node,
        component: "TextField",
        label,
        placeholder: (node.placeholder as string) ?? "YYYY-MM-DD HH:mm",
      };
    }

    case "Select": {
      // Select → TextField showing current value (options visible in label).
      const label = String((node.label as string) ?? "");
      const options = Array.isArray(node.options)
        ? (node.options as Array<Record<string, unknown>>)
            .map((o) => String(o.label ?? o.value ?? ""))
            .join(", ")
        : "";
      return {
        ...node,
        component: "TextField",
        label: options ? `${label} (选项: ${options})` : label,
      };
    }

    case "Slider": {
      // Slider → Column(TextField + Button).  Button triggers reset/default.
      const label = String((node.label as string) ?? "调节");
      const min = String((node.min as number) ?? 0);
      const max = String((node.max as number) ?? 100);
      const value = String((node.value as number) ?? "");
      const id = String((node.id as string) ?? `slider-${nextId()}`);
      const textId = `${id}-value`;
      const btnId = `${id}-reset`;
      return {
        id,
        component: "Column",
        children: [textId, btnId],
        // Injected children — caller must merge these into the flat list
        __preprocess_children: [
          {
            id: textId,
            component: "TextField",
            label: `${label} (${min}–${max})`,
            value,
          },
          {
            id: btnId,
            component: "Button",
            label: "重置",
          },
        ],
      } as Record<string, unknown>;
    }

    case "ChoicePicker": {
      // ChoicePicker → Column of CheckBox items, one per option.
      const label = String((node.label as string) ?? "选择");
      const options = Array.isArray(node.options)
        ? (node.options as Array<Record<string, unknown>>)
        : [];
      const id = String((node.id as string) ?? `picker-${nextId()}`);
      const childIds: string[] = [];
      const childNodes: Record<string, unknown>[] = [];
      for (let i = 0; i < options.length; i++) {
        const opt = options[i];
        const childId = `${id}-opt-${i}`;
        childIds.push(childId);
        childNodes.push({
          id: childId,
          component: "CheckBox",
          label: String(opt.label ?? opt.value ?? ""),
        });
      }
      // Header text + checkbox column
      const headerId = `${id}-hdr`;
      const headerNode: Record<string, unknown> = {
        id: headerId,
        component: "Text",
        text: `**${label}**`,
      };
      return {
        id,
        component: "Column",
        children: [headerId, ...childIds],
        __preprocess_children: [headerNode, ...childNodes],
      } as Record<string, unknown>;
    }

    case "List": {
      // List → Column of Card items or Text items, one per list entry.
      const id = String((node.id as string) ?? `list-${nextId()}`);
      const items = Array.isArray(node.items) ? (node.items as unknown[]) : [];
      const childIds: string[] = [];
      const childNodes: Record<string, unknown>[] = [];
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        const childId = `${id}-item-${i}`;
        childIds.push(childId);
        // Each list item becomes a Text bullet with the item stringified
        const textContent =
          typeof item === "string"
            ? item
            : typeof item === "number" || typeof item === "boolean"
              ? String(item)
              : JSON.stringify(item);
        childNodes.push({
          id: childId,
          component: "Text",
          text: `• ${textContent}`,
        });
      }
      return {
        id,
        component: "Column",
        children: childIds,
        __preprocess_children: childNodes,
      } as Record<string, unknown>;
    }

    case "Tabs": {
      // Tabs → Button row (Row of Buttons) + Column of Tab contents.
      const id = String((node.id as string) ?? `tabs-${nextId()}`);
      const tabs = Array.isArray(node.tabs)
        ? (node.tabs as Array<Record<string, unknown>>)
        : [];
      const headerIds: string[] = [];
      const headerNodes: Record<string, unknown>[] = [];
      for (let i = 0; i < tabs.length; i++) {
        const tab = tabs[i];
        const btnId = `${id}-tab-${i}`;
        headerIds.push(btnId);
        headerNodes.push({
          id: btnId,
          component: "Button",
          label: String(tab.label ?? tab.title ?? `Tab ${i + 1}`),
        });
      }
      return {
        id,
        component: "Column",
        children: headerIds,
        __preprocess_children: headerNodes,
      } as Record<string, unknown>;
    }

    case "Table":
    case "Chart": {
      // Table / Chart → Card with a markdown data table rendered as Text.
      //  1. Chart: extract xAxis + series data points → markdown table
      //  2. Table: use headers + rows → markdown table
      const id = String((node.id as string) ?? `${component.toLowerCase()}-${nextId()}`);
      const title = String((node.title as string) ?? (component === "Chart" ? "图表" : "表格"));
      const markdownText = buildDataMarkdown(node, component);
      const contentId = `${id}-content`;
      return {
        id,
        component: "Card",
        title,
        children: [contentId],
        __preprocess_children: [
          {
            id: contentId,
            component: "Text",
            text: markdownText,
          },
        ],
      } as Record<string, unknown>;
    }

    default: {
      // Completely unknown — best-effort: preserve node but wrap in
      // a Card so at least the data surfaces as text.
      const id = String((node.id as string) ?? `unknown-${nextId()}`);
      return {
        id,
        component: "Card",
        title: `组件: ${component}`,
        children: [],
      };
    }
  }
}

/** Convert a Table or Chart node's structured data into a markdown table string. */
function buildDataMarkdown(
  node: Record<string, unknown>,
  kind: "Table" | "Chart"
): string {
  if (kind === "Table") {
    const headers = Array.isArray(node.headers)
      ? (node.headers as string[])
      : [];
    const rows = Array.isArray(node.rows)
      ? (node.rows as Array<unknown[]>)
      : [];
    if (headers.length === 0 && rows.length === 0) {
      return "_暂无数据_";
    }
    const esc = (v: unknown) => String(v).replace(/\|/g, "\\|");
    const headerLine = headers.map(esc).join(" | ");
    const sepLine = headers.map(() => "---").join(" | ");
    const rowLines = rows.map((r) =>
      (Array.isArray(r) ? r : [r]).map(esc).join(" | ")
    );
    return `\n| ${headerLine} |\n| ${sepLine} |\n${rowLines
      .map((r) => `| ${r} |`)
      .join("\n")}\n`;
  }

  // Chart
  const chartType = String((node.chartType as string) ?? "");
  const series = Array.isArray(node.series)
    ? (node.series as Array<Record<string, unknown>>)
    : [];
  const xAxis = Array.isArray(node.xAxis)
    ? (node.xAxis as unknown[])
    : [];
  const chartData = Array.isArray(node.chartData)
    ? (node.chartData as Array<Record<string, unknown>>)
    : [];

  // chartData is the more direct format: [{key, value}] per data point
  if (chartData.length > 0) {
    const header = Object.keys(chartData[0]).join(" | ");
    const sep = Object.keys(chartData[0]).map(() => "---").join(" | ");
    const rows = chartData.map((d) => Object.values(d).join(" | "));
    return `\n*${chartType}*\n| ${header} |\n| ${sep} |\n${rows
      .map((r) => `| ${r} |`)
      .join("\n")}\n`;
  }

  if (series.length > 0 && xAxis.length > 0) {
    const header = `时间 | ${series.map((s) => String(s.name ?? "series")).join(" | ")}`;
    const sep = `--- | ${series.map(() => "---").join(" | ")}`;
    const rows = xAxis.map((x, i) => {
      const vals = series.map((s) => {
        const data = Array.isArray(s.data) ? s.data : [];
        const v = (data as unknown[])[i];
        return v !== undefined ? String(v) : "-";
      });
      return `${String(x)} | ${vals.join(" | ")}`;
    });
    return `\n*${chartType || "chart"}*\n| ${header} |\n| ${sep} |\n${rows
      .map((r) => `| ${r} |`)
      .join("\n")}\n`;
  }

  return "_暂无数据_";
}

/**
 * Preprocess the components array of an `updateComponents` operation.
 * Mutates the array in place and also returns it for convenience.
 * Injected child nodes (from composite transformations like Slider → Column + TextField + Button)
 * are appended to the components array.
 */
export function preprocessComponents(
  components: unknown[]
): unknown[] {
  if (!Array.isArray(components)) return components;

  let idCounter = 0;
  const nextId = () => `__pp_${++idCounter}`;

  const out: unknown[] = [];
  const injected: Record<string, unknown>[] = [];

  for (const raw of components) {
    if (typeof raw !== "object" || raw === null) {
      out.push(raw);
      continue;
    }
    const node = raw as Record<string, unknown>;
    const preprocessed = preprocessComponent(node, nextId);
    out.push(preprocessed);

    // Composite components (Slider, ChoicePicker, List, Tabs, Table, Chart)
    // carry __preprocess_children that must be flattened into the array.
    if (
      preprocessed.__preprocess_children &&
      Array.isArray(preprocessed.__preprocess_children)
    ) {
      injected.push(
        ...(preprocessed.__preprocess_children as Record<string, unknown>[])
      );
      delete preprocessed.__preprocess_children;
    }
  }

  // Recurse into the injected children — they might also be composite
  if (injected.length > 0) {
    // Run preprocessing recursively on injected nodes, appending any deeper
    // injections.  Repeat until no new injections appear.
    let batch = injected;
    while (batch.length > 0) {
      const subOut: Record<string, unknown>[] = [];
      const subInjected: Record<string, unknown>[] = [];
      for (const raw of batch) {
        const node = raw as Record<string, unknown>;
        const pp = preprocessComponent(node, nextId);
        subOut.push(pp);
        if (
          pp.__preprocess_children &&
          Array.isArray(pp.__preprocess_children)
        ) {
          subInjected.push(
            ...(pp.__preprocess_children as Record<string, unknown>[])
          );
          delete pp.__preprocess_children;
        }
      }
      out.push(...subOut);
      batch = subInjected;
    }
  }

  return out;
}

/**
 * Run preprocessComponents on every `updateComponents` operation in an
 * operations array.  Operations with other types (createSurface / updateDataModel /
 * deleteSurface) are left untouched.
 * Returns a NEW operations array — does not mutate the input.
 */
export function preprocessOperations(
  operations: unknown[]
): unknown[] {
  return operations.map((op) => {
    if (typeof op !== "object" || op === null) return op;
    const o = op as Record<string, unknown>;
    const uc = o.updateComponents;
    if (uc && typeof uc === "object") {
      const ucObj = uc as Record<string, unknown>;
      if (Array.isArray(ucObj.components)) {
        return {
          ...o,
          updateComponents: {
            ...ucObj,
            components: preprocessComponents(ucObj.components),
          },
        };
      }
    }
    return op;
  });
}

/** Type guard: is a decoded SSE content payload an AG-UI ACTIVITY_SNAPSHOT? */
export function isActivitySnapshot(obj: unknown): obj is {
  type: "ACTIVITY_SNAPSHOT";
  messageId: string;
  activityType: string;
  replace: boolean;
  content: { a2ui_operations: A2uiOperation[] };
} {
  if (typeof obj !== "object" || obj === null) return false;
  const o = obj as Record<string, unknown>;
  return (
    o.type === "ACTIVITY_SNAPSHOT" &&
    o.activityType === "a2ui-surface" &&
    typeof o.content === "object" &&
    o.content !== null &&
    Array.isArray((o.content as Record<string, unknown>).a2ui_operations)
  );
}

/** Extract A2UI operations from an ACTIVITY_SNAPSHOT payload (string or object). */
export function extractOperations(
  payload: unknown
): A2uiOperation[] | null {
  if (typeof payload === "string") {
    try {
      payload = JSON.parse(payload);
    } catch {
      return null;
    }
  }
  if (isActivitySnapshot(payload)) {
    return payload.content.a2ui_operations;
  }
  // Tolerate raw { a2ui_operations: [...] } shape too
  if (
    typeof payload === "object" &&
    payload !== null &&
    Array.isArray((payload as Record<string, unknown>).a2ui_operations)
  ) {
    return (payload as Record<string, unknown>).a2ui_operations as A2uiOperation[];
  }
  return null;
}

// ---------------------------------------------------------------------------
// Surface state reducer hook
// ---------------------------------------------------------------------------

export function useA2uiSurfaceState() {
  // useRef survives closure captures; forceUpdate counter drives re-renders.
  // ACTIVITY_SNAPSHOT operations are replace=true (full snapshots), so apply is idempotent.
  const stateRef = React.useRef<A2uiState>(new Map());
  const [, forceUpdate] = useState(0);

  const apply = useCallback((operations: unknown[]) => {
    const pped = preprocessOperations(operations);
    const result: A2uiOperationResult = applyA2uiOperations(stateRef.current, pped);
    stateRef.current = result.state;
    forceUpdate((n) => n + 1);
  }, []);

  const reset = useCallback(() => {
    stateRef.current = new Map();
    forceUpdate((n) => n + 1);
  }, []);

  return { state: stateRef.current, apply, reset };
}

// ---------------------------------------------------------------------------
// Surface → generative-ui spec conversion
// ---------------------------------------------------------------------------

export interface ConvertedSurface {
  spec: unknown | null;
  warnings: string[];
  /** True if any custom (non-standard) component was skipped during conversion. */
  hasCustomComponents: boolean;
}

export function convertSurface(
  surface: A2uiSurfaceState | undefined
): ConvertedSurface {
  if (!surface) {
    return { spec: null, warnings: ["surface not found"], hasCustomComponents: false };
  }
  const result = convertSurfaceToUISpec(surface);
  const unknownWarnings = result.warnings.filter((w) =>
    w.includes("Unknown A2UI component") || w.includes("was skipped")
  );
  return {
    spec: result.spec,
    warnings: result.warnings,
    hasCustomComponents: unknownWarnings.length > 0,
  };
}

// ---------------------------------------------------------------------------
// Bridge surface component
// ---------------------------------------------------------------------------

export interface A2uiBridgeSurfaceProps {
  /** AG-UI ACTIVITY_SNAPSHOT content — raw JSON string or parsed object. */
  snapshot: unknown;
  /** Fallback renderer for surfaces with custom (non-standard) components. */
  children?: React.ReactNode;
  className?: string;
}

/**
 * Renders A2UI content through assistant-ui's native generative UI path.
 *
 * Flow:
 *  1. Parse snapshot → extract operations
 *  2. applyA2uiOperations → accumulate surface state
 *  3. convertSurfaceToUISpec → spec tree + warnings
 *  4a. If no unknown components → renderGenerativeUI(spec, library)
 *  4b. If unknown components (Chart, Slider, etc.) → render children (legacy A2UIRenderer)
 */
export function A2uiBridgeSurface({
  snapshot,
  children,
  className = "",
}: A2uiBridgeSurfaceProps) {
  const ops = useMemo(() => extractOperations(snapshot), [snapshot]);
  const { state, apply } = useA2uiSurfaceState();

  // Apply new ops whenever they arrive
  useEffect(() => {
    if (!ops || ops.length === 0) return;
    apply(ops);
  }, [ops, apply]);

  // Find the latest surface
  const surfaceId = useMemo(() => {
    if (!ops || ops.length === 0) return null;
    // Last operation's surfaceId wins
    for (let i = ops.length - 1; i >= 0; i--) {
      const op = ops[i] as Record<string, unknown>;
      const inner =
        op.createSurface ||
        op.updateComponents ||
        op.updateDataModel ||
        op.deleteSurface;
      if (inner && typeof inner === "object" && "surfaceId" in inner) {
        return (inner as Record<string, unknown>).surfaceId as string;
      }
    }
    return null;
  }, [ops]);

  // Convert
  const converted = useMemo<ConvertedSurface>(() => {
    if (!surfaceId) return { spec: null, warnings: [], hasCustomComponents: false };
    return convertSurface(state.get(surfaceId));
  }, [state, surfaceId]);

  if (!ops || ops.length === 0) {
    return <div className={className}>{children}</div>;
  }

  // Fallback path: surface uses custom components not supported by native converter
  if (converted.hasCustomComponents) {
    // Log warnings once (dev only)
    if (process.env.NODE_ENV === "development") {
      // eslint-disable-next-line no-console
      console.warn(
        "[A2uiBridgeSurface] falling back to legacy renderer due to:",
        converted.warnings
      );
    }
    return <div className={className}>{children}</div>;
  }

  if (!converted.spec) {
    return <div className={className}>{children}</div>;
  }

  // Native generative-ui render path
  return (
    <div className={`a2ui-generative-surface ${className}`}>
      {renderGenerativeUI(converted.spec, defaultGenerativeUILibrary)}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Toolkit factory — for runtime registration once AG-UI runtime is wired up.
// Currently returns a stub (present tool is **not** registered as an actual
// frontend tool because we haven't migrated away from useLocalRuntime yet).
// ---------------------------------------------------------------------------

export function createA2uiToolkitStub() {
  // Intentionally returns null — the real toolkit construction depends on
  // being inside an AG-UI runtime context (useAgUiRuntime), which this
  // project does not yet use. When Layer 4 (runtime migration) lands, this
  // factory will be replaced with a live JSONGenerativeUI.present() toolkit.
  return {
    toolkit: null as null,
    __placeholder: true,
  };
}
