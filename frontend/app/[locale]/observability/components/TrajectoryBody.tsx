// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useRef, useState } from "react";
import { App, Segmented } from "antd";
import { useTranslation } from "react-i18next";
import { StandardButton } from "@/components/common/StandardButton";
import { trajectoryService } from "@/services/trajectoryService";
import { BodyCache, invalidatesTrajectory } from "@/lib/trajectory";
import type { ContentReference } from "@/types/trajectory";
import { TrajectoryError } from "./TrajectoryFeedback";

export function TrajectoryBody({
  reference,
  slot,
  conversationId,
  nodeId,
  cache,
  onLoaded,
  onInvalidated,
}: {
  reference: ContentReference;
  slot: string;
  conversationId: string;
  nodeId: string;
  cache: BodyCache;
  onLoaded: () => void;
  onInvalidated?: (error: unknown) => void;
}) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [collapsed, setCollapsed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [mode, setMode] = useState("text");
  const [chunk, setChunk] = useState<{
    offset: number;
    next: number;
    complete: boolean;
    text: string;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const request = useRef<AbortController | null>(null);
  const retryOffset = useRef(0);
  useEffect(() => () => request.current?.abort(), []);
  const text = chunk?.text ?? reference.text ?? reference.preview ?? "";
  const complete = chunk?.complete ?? reference.complete;
  const offset = chunk?.offset ?? 0;
  let formatted = text;
  if (mode === "json") {
    try {
      formatted = JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      formatted = JSON.stringify({ content: text }, null, 2);
    }
  }
  async function load(offset: number) {
    if (!reference.content_id) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    retryOffset.current = offset;
    setLoading(true);
    setError(null);
    try {
      const key = `${nodeId}:${slot}:${offset}`;
      // Revalidate each explicit read; the bounded cache supports local search only.
      const value = await trajectoryService.content(
        conversationId,
        reference.content_id,
        offset,
        controller.signal
      );
      if (controller.signal.aborted) return;
      cache.set(key, value.text);
      setChunk({
        offset: value.offset,
        next: value.next_offset,
        text: value.text,
        complete: value.complete,
      });
      onLoaded();
      setExpanded(true);
    } catch (cause) {
      if (!controller.signal.aborted) {
        if (invalidatesTrajectory(cause)) {
          cache.clear();
          onInvalidated?.(cause);
        }
        setError(cause);
      }
    } finally {
      if (request.current === controller && !controller.signal.aborted)
        setLoading(false);
    }
  }
  return (
    <section className="trajectory-body">
      <header>
        <button
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((value) => !value)}
        >
          {collapsed ? "▸" : "▾"} {t(`trajectory.${slot}`)}
        </button>
        <div className="flex flex-wrap items-center gap-1">
          <Segmented
            size="small"
            value={mode}
            onChange={setMode}
            options={[
              { label: t("trajectory.text"), value: "text" },
              { label: "JSON", value: "json" },
            ]}
          />
          <StandardButton
            size="small"
            disabled={!text && reference.availability !== "available"}
            onClick={() => {
              void navigator.clipboard.writeText(formatted).then(
                () => message.success(t("trajectory.copied")),
                () => message.error(t("trajectory.copyFailed"))
              );
            }}
          >
            {t("trajectory.copy")}
          </StandardButton>
        </div>
      </header>
      {!collapsed && (
        <>
          {reference.availability !== "available" ? (
            <p className="p-3 text-xs text-gray-500">
              {t(`trajectory.bodyAvailability.${reference.availability}`, {
                defaultValue: t("trajectory.bodyUnavailable"),
              })}
            </p>
          ) : (
            <>
              <p className="px-3 py-1 text-xs text-gray-500">
                {t("trajectory.characters", {
                  count: reference.char_count ?? Array.from(text).length,
                })}{" "}
                ·{" "}
                {t(
                  offset === 0 && complete
                    ? "trajectory.fullContent"
                    : "trajectory.contentRange",
                  {
                    start: offset,
                    end: chunk?.next ?? new TextEncoder().encode(text).length,
                    total: reference.byte_count ?? "—",
                  }
                )}
              </p>
              <pre
                className={
                  expanded ? "trajectory-body-full" : "trajectory-body-preview"
                }
              >
                {formatted || t("trajectory.emptyBody")}
              </pre>
              <div className="flex flex-wrap gap-2 p-2">
                <StandardButton
                  loading={loading}
                  onClick={() => {
                    if (!reference.complete && !chunk) void load(0);
                    else setExpanded((value) => !value);
                  }}
                >
                  {t(
                    expanded
                      ? "trajectory.collapseContent"
                      : "trajectory.expandContent"
                  )}
                </StandardButton>
                {chunk && chunk.offset > 0 && (
                  <StandardButton
                    disabled={loading}
                    onClick={() => void load(0)}
                  >
                    {t("trajectory.firstChunk")}
                  </StandardButton>
                )}
                {!complete && reference.content_id && (
                  <StandardButton
                    loading={loading}
                    onClick={() => void load(chunk ? chunk.next : 0)}
                  >
                    {t("trajectory.nextChunk")}
                  </StandardButton>
                )}
              </div>
            </>
          )}
          {error != null && (
            <TrajectoryError
              error={error}
              retry={() => void load(retryOffset.current)}
            />
          )}
        </>
      )}
    </section>
  );
}
