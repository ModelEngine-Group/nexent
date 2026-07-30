"use client";

import { useEffect, useMemo, useRef } from "react";
import { useAui } from "@assistant-ui/react";
import {
  A2uiSurface,
  basicCatalog,
  type ReactComponentImplementation,
} from "@a2ui/react/v0_9";
import {
  A2uiMessageSchema,
  MessageProcessor,
  type A2uiClientAction,
  type A2uiMessage,
} from "@a2ui/web_core/v0_9";

export const A2UI_BASIC_CATALOG_ID =
  "https://a2ui.org/specification/v0_9/basic_catalog.json";

export interface A2UIEnvelope {
  protocolVersion: "v0.9";
  catalogId: typeof A2UI_BASIC_CATALOG_ID;
  surfaceId: string;
  message: A2uiMessage;
}

export interface A2UISurfaceData {
  surfaceId: string;
  messages: A2UIEnvelope[];
  error?: string;
}

const encodedSize = (value: unknown): number =>
  new TextEncoder().encode(JSON.stringify(value)).length;

export function parseA2UIEnvelope(value: unknown): A2UIEnvelope {
  if (encodedSize(value) > 256 * 1024) {
    throw new Error("A2UI message exceeds 256 KiB");
  }
  if (!value || typeof value !== "object") {
    throw new Error("Invalid A2UI envelope");
  }
  const envelope = value as Partial<A2UIEnvelope>;
  if (
    envelope.protocolVersion !== "v0.9" ||
    envelope.catalogId !== A2UI_BASIC_CATALOG_ID ||
    typeof envelope.surfaceId !== "string" ||
    !envelope.surfaceId
  ) {
    throw new Error("Unsupported A2UI protocol or catalog");
  }
  const parsed = A2uiMessageSchema.safeParse(envelope.message);
  if (!parsed.success) {
    throw new Error("A2UI schema validation failed");
  }
  return {
    protocolVersion: "v0.9",
    catalogId: A2UI_BASIC_CATALOG_ID,
    surfaceId: envelope.surfaceId,
    message: parsed.data,
  };
}

export function createA2UIDataPart(data: A2UISurfaceData) {
  return {
    type: "data" as const,
    name: "a2ui-surface",
    data,
  };
}

const actionFallbackLabel = (): string =>
  typeof document !== "undefined" &&
  document.documentElement.lang.toLowerCase().startsWith("zh")
    ? "执行操作"
    : "Perform action";

const cleanActionLabel = (value: unknown): string => {
  if (typeof value !== "string") return actionFallbackLabel();
  const label = value
    .replace(/[\p{Cc}\p{Cf}\p{Cs}]+/gu, " ")
    .replace(/\s+/gu, " ")
    .trim()
    .slice(0, 256);
  return label || actionFallbackLabel();
};

const findActionLabel = (
  messages: readonly A2UIEnvelope[],
  action: A2uiClientAction
): string => {
  const components = new Map<string, Record<string, unknown>>();
  for (const envelope of messages) {
    if (!("updateComponents" in envelope.message)) continue;
    for (const component of envelope.message.updateComponents.components) {
      const record = component as Record<string, unknown>;
      if (typeof record.id === "string") {
        components.set(record.id, { ...components.get(record.id), ...record });
      }
    }
  }
  const source = components.get(action.sourceComponentId);
  if (source?.component !== "Button" || typeof source.child !== "string") {
    return actionFallbackLabel();
  }
  const label = components.get(source.child);
  return cleanActionLabel(label?.component === "Text" ? label.text : undefined);
};

export function A2UISurface({ surfaceId, messages, error }: A2UISurfaceData) {
  const aui = useAui();
  const disposalTimers = useRef(
    new WeakMap<
      MessageProcessor<ReactComponentImplementation>,
      ReturnType<typeof setTimeout>
    >()
  );
  const runtime = useMemo(() => {
    if (error) return { processor: null, error };
    try {
      const processor = new MessageProcessor<ReactComponentImplementation>(
        [basicCatalog],
        async (action) => {
          const label = findActionLabel(messages, action);
          aui.thread().append({
            role: "user",
            content: [
              { type: "text", text: label },
              {
                type: "data",
                name: "a2ui-action",
                data: { version: "v0.9", action },
              },
            ],
            runConfig: aui.composer().getState().runConfig,
            startRun: true,
          });
        }
      );
      for (const envelope of messages) {
        if (envelope.surfaceId !== surfaceId) {
          throw new Error("A2UI Surface messages do not match");
        }
        processor.processMessages([envelope.message]);
      }
      return { processor, error: undefined };
    } catch {
      return {
        processor: null,
        error: "Interactive content cannot be displayed",
      };
    }
  }, [aui, error, messages, surfaceId]);

  useEffect(() => {
    const processor = runtime.processor;
    if (!processor) return;
    const timers = disposalTimers.current;

    const pendingDisposal = timers.get(processor);
    if (pendingDisposal) {
      clearTimeout(pendingDisposal);
      timers.delete(processor);
    }

    return () => {
      const timer = setTimeout(() => {
        processor.model.dispose();
        timers.delete(processor);
      }, 0);
      timers.set(processor, timer);
    };
  }, [runtime]);

  const surface = runtime.processor?.model.getSurface(surfaceId);
  if (runtime.error || !surface) {
    return (
      <div className="my-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
        交互内容无法显示
      </div>
    );
  }
  return (
    <div className="my-3 rounded-lg border bg-background p-3">
      <A2uiSurface surface={surface} />
    </div>
  );
}
