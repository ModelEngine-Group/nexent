"use client";

import { useSyncExternalStore } from "react";
import {
  A2uiSurface,
  type ReactComponentImplementation,
} from "@a2ui/react/v0_9";
import {
  A2uiClientActionSchema,
  A2uiMessageSchema,
  MessageProcessor,
  type A2uiClientAction,
  type A2uiMessage,
} from "@a2ui/web_core/v0_9";
import { nexentCatalog } from "./catalog";
import {
  clearAllA2UIFormSubmissionState,
  clearA2UIFormSubmissionState,
  clearA2UIFormSubmissions,
  consumeA2UIFormSubmission,
  isA2UIFormSubmitted,
  markA2UIFormSubmissionAccepted,
  registerA2UISurfaceSession,
  type A2UIFormSubmissionState,
  type A2UIFormValues,
} from "./form-submission-store";

export const A2UI_ACTION_EVENT = "nexent:a2ui-action";

export interface A2UIEnvelope {
  protocolVersion: "v0.9";
  catalogId: "nexent.v1";
  surfaceId: string;
  message: A2uiMessage;
}

export interface A2UIActionSubmission {
  submissionId: string;
  message: { version: "v0.9"; action: A2uiClientAction };
  formSubmission?: { values: A2UIFormValues };
}

interface RuntimeEntry {
  processor: MessageProcessor<ReactComponentImplementation>;
  seen: Set<string>;
  renderedSurfaces: Set<string>;
  surfaceErrors: Map<string, string>;
  actionComponents: Map<string, Record<string, unknown>>;
  listeners: Set<() => void>;
  version: number;
}

interface PendingAction {
  sessionKey: string;
  submission: A2UIActionSubmission;
  startupTimeout?: ReturnType<typeof setTimeout>;
}

interface ActionWaiter {
  sessionKey: string;
  resolve: () => void;
  reject: (error: Error) => void;
}

const runtimes = new Map<string, RuntimeEntry>();
const aliases = new Map<string, string>();
const pendingActions = new Map<string, PendingAction>();
const inFlightActions = new Map<string, string>();
const actionWaiters = new Map<string, ActionWaiter>();
const allowedComponents = new Set([
  "Text",
  "Image",
  "Icon",
  "Button",
  "Card",
  "Row",
  "Column",
  "Divider",
  "DataTable",
  "Chart",
  "Form",
  "ApprovalCard",
  "ArtifactCard",
]);
const commonComponentKeys = new Set([
  "id",
  "component",
  "accessibility",
  "weight",
]);
const componentContracts: Record<
  string,
  { required: readonly string[]; optional: readonly string[] }
> = {
  Text: { required: ["text"], optional: ["variant"] },
  Image: {
    required: ["url"],
    optional: ["description", "fit", "variant"],
  },
  Icon: { required: ["name"], optional: [] },
  Button: {
    required: ["child", "action"],
    optional: ["variant", "checks"],
  },
  Card: { required: ["child"], optional: [] },
  Row: { required: ["children"], optional: ["justify", "align"] },
  Column: { required: ["children"], optional: ["justify", "align"] },
  Divider: { required: [], optional: ["axis"] },
  DataTable: {
    required: ["columns", "rows"],
    optional: ["caption"],
  },
  Chart: {
    required: ["chartType", "data", "valueKey"],
    optional: ["xKey", "title"],
  },
  Form: {
    required: ["fields", "action"],
    optional: ["title", "submitLabel"],
  },
  ApprovalCard: {
    required: ["title", "approveAction", "rejectAction"],
    optional: ["description", "approveLabel", "rejectLabel"],
  },
  ArtifactCard: {
    required: ["title", "url"],
    optional: ["description"],
  },
};
const forbiddenKeys = new Set([
  "style",
  "className",
  "css",
  "html",
  "dangerouslySetInnerHTML",
  "api",
  "endpoint",
]);
const urlKeys = new Set(["url", "href", "downloadUrl", "previewUrl"]);
const htmlPattern =
  /<\s*\/?\s*(?:script|style|iframe|object|embed|html|body|svg|[a-z][a-z0-9-]*)\b/i;
const actionLabelLimit = 256;
const legacyActionPrefix = /^\[(?:A2UI action|交互操作)\](?:\s|$)/;

const getActionFallbackLabel = (): string =>
  typeof document !== "undefined" &&
  document.documentElement.lang.toLowerCase().startsWith("zh")
    ? "执行操作"
    : "Perform action";

export const normalizeA2UIActionLabel = (value: unknown): string => {
  if (typeof value !== "string") return getActionFallbackLabel();
  const normalized = value
    .replace(/[\p{Cc}\p{Cf}\p{Cs}]+/gu, " ")
    .replace(/\s+/gu, " ")
    .trim()
    .slice(0, actionLabelLimit);
  return normalized || getActionFallbackLabel();
};

export const normalizeLegacyA2UIActionText = (value: string): string =>
  legacyActionPrefix.test(value) ? getActionFallbackLabel() : value;

const actionComponentKey = (surfaceId: string, componentId: string): string =>
  `${surfaceId}\u0000${componentId}`;

const releaseActionLock = (submissionId: string): void => {
  for (const [key, value] of inFlightActions) {
    if (value === submissionId) inFlightActions.delete(key);
  }
};

const findActionName = (value: unknown): string | undefined => {
  if (Array.isArray(value)) {
    for (const child of value) {
      const result = findActionName(child);
      if (result) return result;
    }
    return undefined;
  }
  if (!value || typeof value !== "object") return undefined;
  const record = value as Record<string, unknown>;
  if (typeof record.name === "string") return record.name;
  for (const child of Object.values(record)) {
    const result = findActionName(child);
    if (result) return result;
  }
  return undefined;
};

const rememberActionComponents = (
  entry: RuntimeEntry,
  surfaceId: string,
  message: A2uiMessage
): void => {
  if (!("updateComponents" in message)) return;
  for (const component of message.updateComponents.components as Array<
    Record<string, unknown>
  >) {
    if (typeof component.id !== "string") continue;
    const key = actionComponentKey(surfaceId, component.id);
    entry.actionComponents.set(key, {
      ...entry.actionComponents.get(key),
      ...component,
    });
  }
};

const resolveActionLabel = (
  entry: RuntimeEntry,
  action: A2uiClientAction
): string => {
  const component = entry.actionComponents.get(
    actionComponentKey(action.surfaceId, action.sourceComponentId)
  );
  if (!component) return getActionFallbackLabel();

  let label: unknown;
  if (component.component === "Form") {
    label = component.submitLabel ?? "Submit";
  } else if (component.component === "ApprovalCard") {
    if (action.name === findActionName(component.approveAction)) {
      label = component.approveLabel ?? "Approve";
    } else if (action.name === findActionName(component.rejectAction)) {
      label = component.rejectLabel ?? "Reject";
    }
  } else if (component.component === "Button") {
    const childId = component.child;
    const child =
      typeof childId === "string"
        ? entry.actionComponents.get(
            actionComponentKey(action.surfaceId, childId)
          )
        : undefined;
    if (child?.component === "Text") label = child.text;
  }
  return normalizeA2UIActionLabel(label);
};

const encodedSize = (value: unknown): number =>
  new TextEncoder().encode(JSON.stringify(value)).length;

const validateValueSafety = (value: unknown, depth = 0): void => {
  if (depth > 32) throw new Error("A2UI value nesting is too deep");
  if (Array.isArray(value)) {
    value.forEach((item) => validateValueSafety(item, depth + 1));
    return;
  }
  if (!value || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    if (forbiddenKeys.has(key))
      throw new Error("A2UI contains a forbidden property");
    if (typeof child === "string") {
      const normalized = child.trim().toLowerCase();
      if (normalized.includes("javascript:") || htmlPattern.test(child)) {
        throw new Error("A2UI contains unsafe markup or a script URL");
      }
      const isSameOriginPath =
        child.startsWith("/") &&
        !child.startsWith("//") &&
        !child.includes("\\");
      if (urlKeys.has(key) && !isSameOriginPath) {
        let parsed: URL;
        try {
          parsed = new URL(child);
        } catch {
          throw new Error("A2UI URLs must be same-origin paths or HTTPS");
        }
        if (parsed.protocol !== "https:") {
          throw new Error("A2UI URLs must be same-origin paths or HTTPS");
        }
      }
    }
    if (key === "context" && encodedSize(child) > 64 * 1024) {
      throw new Error("A2UI action context exceeds 64 KiB");
    }
    validateValueSafety(child, depth + 1);
  }
};

const validateComponentGraph = (
  components: Array<Record<string, unknown>>
): void => {
  if (components.length > 200)
    throw new Error("A2UI surface exceeds 200 components");
  const graph = new Map<string, string[]>();
  for (const component of components) {
    const id = component.id;
    const componentType = component.component;
    if (typeof id !== "string" || graph.has(id)) {
      throw new Error("A2UI component ids must be unique strings");
    }
    if (
      typeof componentType !== "string" ||
      !allowedComponents.has(componentType)
    ) {
      throw new Error("A2UI component is outside the nexent.v1 catalog");
    }
    const contract = componentContracts[componentType];
    const missing = contract.required.filter(
      (propertyName) => !(propertyName in component)
    );
    if (missing.length > 0) {
      throw new Error("A2UI component is missing required properties");
    }
    const allowedKeys = new Set([
      ...commonComponentKeys,
      ...contract.required,
      ...contract.optional,
    ]);
    if (Object.keys(component).some((key) => !allowedKeys.has(key))) {
      throw new Error("A2UI component has unsupported properties");
    }
    if (
      (componentType === "Card" || componentType === "Button") &&
      (typeof component.child !== "string" || !component.child)
    ) {
      throw new Error("A2UI component child must be a component id");
    }
    if (
      (componentType === "Row" || componentType === "Column") &&
      (!Array.isArray(component.children) ||
        component.children.some((child) => typeof child !== "string" || !child))
    ) {
      throw new Error("A2UI layout children must be component ids");
    }
    const references = [
      component.child,
      ...(Array.isArray(component.children) ? component.children : []),
    ].filter((item): item is string => typeof item === "string");
    graph.set(id, references);
    if (
      componentType === "DataTable" &&
      Array.isArray(component.rows) &&
      component.rows.length > 500
    ) {
      throw new Error("A2UI table exceeds 500 rows");
    }
    if (
      componentType === "Chart" &&
      Array.isArray(component.data) &&
      component.data.length > 1000
    ) {
      throw new Error("A2UI chart exceeds 1000 data points");
    }
    if (componentType === "Form") {
      const allowedFields = new Set([
        "text",
        "textarea",
        "number",
        "select",
        "checkbox",
        "date",
      ]);
      if (
        !Array.isArray(component.fields) ||
        component.fields.some(
          (field) =>
            !field ||
            typeof field !== "object" ||
            !allowedFields.has(String((field as { type?: unknown }).type))
        )
      ) {
        throw new Error("A2UI form contains an unsupported field");
      }
    }
    validateValueSafety(component);
  }
  if (!graph.has("root"))
    throw new Error("A2UI surface requires a root component");
  const visit = (id: string, path: Set<string>, depth: number): void => {
    if (depth > 16) throw new Error("A2UI component nesting exceeds 16");
    if (path.has(id))
      throw new Error("A2UI component references contain a cycle");
    if (!graph.has(id)) throw new Error("A2UI component reference is missing");
    for (const child of graph.get(id) ?? []) {
      visit(child, new Set([...path, id]), depth + 1);
    }
  };
  visit("root", new Set(), 1);
};

const validateMessageSafety = (message: A2uiMessage): void => {
  if ("updateComponents" in message) {
    validateComponentGraph(
      message.updateComponents.components as Array<Record<string, unknown>>
    );
  } else {
    validateValueSafety(message);
  }
};

const createRuntime = (sessionKey: string): RuntimeEntry => {
  const entry = {} as RuntimeEntry;
  entry.seen = new Set();
  entry.renderedSurfaces = new Set();
  entry.surfaceErrors = new Map();
  entry.actionComponents = new Map();
  entry.listeners = new Set();
  entry.version = 0;
  entry.processor = new MessageProcessor([nexentCatalog], async (rawAction) => {
    const result = A2uiClientActionSchema.safeParse(rawAction);
    if (!result.success || typeof window === "undefined") return;
    const action = result.data;
    const component = entry.actionComponents.get(
      actionComponentKey(action.surfaceId, action.sourceComponentId)
    );
    const isForm = component?.component === "Form";
    if (
      isForm &&
      isA2UIFormSubmitted(action.surfaceId, action.sourceComponentId)
    ) {
      return;
    }
    const actionKey = `${sessionKey}:${action.surfaceId}:${action.sourceComponentId}:${action.name}`;
    if (inFlightActions.has(actionKey)) return;
    const submissionId = crypto.randomUUID();
    inFlightActions.set(actionKey, submissionId);
    const formValues = consumeA2UIFormSubmission(
      action.surfaceId,
      action.sourceComponentId
    );
    const submission: A2UIActionSubmission = {
      submissionId,
      message: { version: "v0.9", action },
      ...(formValues ? { formSubmission: { values: formValues } } : {}),
    };
    let accepted: Promise<void> | undefined;
    if (isForm) {
      accepted = new Promise<void>((resolve, reject) => {
        actionWaiters.set(submissionId, { sessionKey, resolve, reject });
      });
    }
    const pending: PendingAction = { sessionKey, submission };
    pending.startupTimeout = setTimeout(() => {
      failA2UIAction(submissionId, new Error("A2UI action was not started"));
    }, 10_000);
    pendingActions.set(sessionKey, pending);
    window.dispatchEvent(
      new CustomEvent(A2UI_ACTION_EVENT, {
        detail: {
          sessionKey,
          submissionId,
          actionLabel: resolveActionLabel(entry, action),
        },
      })
    );
    if (accepted) await accepted;
  });
  runtimes.set(sessionKey, entry);
  return entry;
};

const getRuntime = (sessionKey: string): RuntimeEntry =>
  runtimes.get(resolveSessionKey(sessionKey)) ??
  createRuntime(resolveSessionKey(sessionKey));

const resolveSessionKey = (sessionKey: string): string => {
  let current = sessionKey;
  const visited = new Set<string>();
  while (aliases.has(current) && !visited.has(current)) {
    visited.add(current);
    current = aliases.get(current) as string;
  }
  return current;
};

export function aliasA2UISession(
  sessionKey: string,
  conversationId: string
): void {
  const canonical = resolveSessionKey(sessionKey);
  aliases.set(sessionKey, canonical);
  aliases.set(conversationId, canonical);
}

export function isSameA2UISession(left: string, right: string): boolean {
  return resolveSessionKey(left) === resolveSessionKey(right);
}

export function processA2UIEnvelope(
  sessionKey: string,
  rawEnvelope: unknown
): { surfaceId?: string; error?: string; shouldRender?: boolean } {
  let surfaceId: string | undefined;
  try {
    if (encodedSize(rawEnvelope) > 256 * 1024) {
      throw new Error("A2UI message exceeds 256 KiB");
    }
    if (!rawEnvelope || typeof rawEnvelope !== "object")
      throw new Error("Invalid A2UI envelope");
    const envelope = rawEnvelope as Partial<A2UIEnvelope>;
    if (
      envelope.protocolVersion !== "v0.9" ||
      envelope.catalogId !== "nexent.v1"
    ) {
      throw new Error("Unsupported A2UI protocol or catalog");
    }
    if (typeof envelope.surfaceId !== "string")
      throw new Error("Missing A2UI surface id");
    surfaceId = envelope.surfaceId;
    const parsed = A2uiMessageSchema.safeParse(envelope.message);
    if (!parsed.success) throw new Error("A2UI schema validation failed");
    validateMessageSafety(parsed.data);
    const entry = getRuntime(sessionKey);
    registerA2UISurfaceSession(
      resolveSessionKey(sessionKey),
      envelope.surfaceId
    );
    const dedupeKey = JSON.stringify(parsed.data);
    if (!entry.seen.has(dedupeKey)) {
      rememberActionComponents(entry, envelope.surfaceId, parsed.data);
      entry.processor.processMessages([parsed.data]);
      entry.seen.add(dedupeKey);
      entry.version += 1;
      entry.listeners.forEach((listener) => listener());
    }
    const shouldRender = !entry.renderedSurfaces.has(envelope.surfaceId);
    entry.renderedSurfaces.add(envelope.surfaceId);
    return { surfaceId: envelope.surfaceId, shouldRender };
  } catch (error) {
    const message =
      error instanceof Error
        ? error.message
        : "Interactive content cannot be displayed";
    if (surfaceId) {
      const entry = getRuntime(sessionKey);
      entry.surfaceErrors.set(surfaceId, message);
      entry.version += 1;
      entry.listeners.forEach((listener) => listener());
    }
    return {
      surfaceId,
      error: message,
    };
  }
}

export function consumePendingA2UIAction(
  sessionKey: string
): A2UIActionSubmission | null {
  const canonical = resolveSessionKey(sessionKey);
  const pending = pendingActions.get(canonical);
  if (!pending) return null;
  pendingActions.delete(canonical);
  if (pending.startupTimeout) clearTimeout(pending.startupTimeout);
  return pending.submission;
}

export function completeA2UIAction(submissionId: string | undefined): void {
  if (!submissionId) return;
  if (actionWaiters.has(submissionId)) {
    failA2UIAction(
      submissionId,
      new Error("A2UI Form submission was not accepted")
    );
    return;
  }
  releaseActionLock(submissionId);
}

export function failA2UIAction(
  submissionId: string | undefined,
  error = new Error("A2UI action failed")
): void {
  if (!submissionId) return;
  for (const [sessionKey, pending] of pendingActions) {
    if (pending.submission.submissionId === submissionId) {
      if (pending.startupTimeout) clearTimeout(pending.startupTimeout);
      pendingActions.delete(sessionKey);
    }
  }
  const waiter = actionWaiters.get(submissionId);
  if (waiter) {
    actionWaiters.delete(submissionId);
    waiter.reject(error);
  }
  releaseActionLock(submissionId);
}

export function markA2UIFormSubmitted(
  sessionKey: string,
  state: A2UIFormSubmissionState
): void {
  const canonical = resolveSessionKey(sessionKey);
  markA2UIFormSubmissionAccepted(canonical, state);
  acceptA2UIAction(state.submissionId, canonical);
}

export function acceptA2UIAction(
  submissionId: string | undefined,
  sessionKey?: string
): void {
  if (!submissionId) return;
  const waiter = actionWaiters.get(submissionId);
  const canonical = sessionKey ? resolveSessionKey(sessionKey) : undefined;
  if (
    waiter &&
    (canonical === undefined ||
      resolveSessionKey(waiter.sessionKey) === canonical)
  ) {
    actionWaiters.delete(submissionId);
    waiter.resolve();
    releaseActionLock(submissionId);
  }
}

export function disposeA2UISession(sessionKey: string): void {
  const canonical = resolveSessionKey(sessionKey);
  const entry = runtimes.get(canonical);
  if (entry) {
    entry.renderedSurfaces.forEach(clearA2UIFormSubmissions);
    entry.processor.model.dispose();
    runtimes.delete(canonical);
  }
  const pending = pendingActions.get(canonical);
  if (pending) failA2UIAction(pending.submission.submissionId);
  for (const [submissionId, waiter] of actionWaiters) {
    if (resolveSessionKey(waiter.sessionKey) === canonical) {
      failA2UIAction(submissionId);
    }
  }
  clearA2UIFormSubmissionState(canonical);
  for (const [key, value] of aliases) {
    if (key === canonical || value === canonical) aliases.delete(key);
  }
  for (const key of inFlightActions.keys()) {
    if (key.startsWith(`${canonical}:`)) inFlightActions.delete(key);
  }
}

export function disposeAllA2UISessions(): void {
  const sessionKeys = new Set<string>([
    ...runtimes.keys(),
    ...pendingActions.keys(),
    ...aliases.values(),
    ...Array.from(actionWaiters.values(), (waiter) => waiter.sessionKey),
  ]);
  sessionKeys.forEach(disposeA2UISession);
  runtimes.clear();
  pendingActions.clear();
  actionWaiters.clear();
  inFlightActions.clear();
  aliases.clear();
  clearAllA2UIFormSubmissionState();
}

export function createA2UIDataPart(
  sessionKey: string,
  surfaceId: string,
  error?: string
) {
  return {
    type: "data" as const,
    name: "a2ui-surface",
    data: { sessionKey, surfaceId, error },
  };
}

export function A2UISurface({
  sessionKey,
  surfaceId,
  error,
}: {
  sessionKey: string;
  surfaceId: string;
  error?: string;
}) {
  const entry = getRuntime(sessionKey);
  useSyncExternalStore(
    (listener) => {
      entry.listeners.add(listener);
      return () => entry.listeners.delete(listener);
    },
    () => entry.version,
    () => entry.version
  );
  if (error || entry.surfaceErrors.has(surfaceId)) {
    return (
      <div className="my-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
        交互内容无法显示
      </div>
    );
  }
  const surface = entry.processor.model.getSurface(surfaceId);
  if (!surface) {
    return (
      <div className="my-3 rounded-lg border p-3 text-sm text-muted-foreground">
        正在加载交互内容…
      </div>
    );
  }
  return (
    <div className="my-3 rounded-lg border bg-background p-3">
      <A2uiSurface surface={surface} />
    </div>
  );
}
