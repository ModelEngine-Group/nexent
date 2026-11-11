// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useRef, useState } from "react";
import { Tag } from "antd";
import { useTranslation } from "react-i18next";
import { BodyCache, formatMetric, formatTraceTime } from "@/lib/trajectory";
import type { TrajectoryNode } from "@/types/trajectory";
import { TrajectoryBody } from "./TrajectoryBody";

export function TrajectoryNodeDetail({
  node,
  conversationId,
  cache,
  onParent,
  onLoaded,
  onInvalidated,
}: {
  node: TrajectoryNode;
  conversationId: string;
  cache: BodyCache;
  onParent: (id: string) => void;
  onLoaded: () => void;
  onInvalidated?: (error: unknown) => void;
}) {
  const { t } = useTranslation();
  const container = useRef<HTMLDivElement>(null);
  const [info, setInfo] = useState(true);
  useEffect(() => {
    container.current?.scrollTo?.(0, 0);
  }, [node.id]);
  const metrics = [
    ...(node.kind !== "tool"
      ? [
          [t("trajectory.inputTokens"), formatMetric(node.usage?.input, 0)],
          [t("trajectory.outputTokens"), formatMetric(node.usage?.output, 0)],
          [t("trajectory.totalTokens"), formatMetric(node.usage?.total, 0)],
        ]
      : []),
    [
      t("trajectory.duration"),
      `${formatMetric(node.duration_ms == null ? null : node.duration_ms / 1000)} s`,
    ],
    ...(node.kind === "model"
      ? [
          [t("trajectory.ttft"), `${formatMetric(node.ttft_ms)} ms`],
          [
            t("trajectory.throughput"),
            `${formatMetric(node.throughput)} Token/s`,
          ],
        ]
      : []),
    ...(node.kind === "agent"
      ? [
          [t("trajectory.modelCalls"), formatMetric(node.model_call_count, 0)],
          [t("trajectory.toolCalls"), formatMetric(node.tool_call_count, 0)],
        ]
      : []),
  ];
  const known = node.usage?.known;
  const input = node.usage?.input ?? known?.input;
  const output = node.usage?.output ?? known?.output;
  return (
    <div className="trajectory-node-detail" ref={container}>
      <header>
        <h2>{node.name}</h2>
        <Tag
          color={
            node.kind === "agent"
              ? "purple"
              : node.kind === "model"
                ? "blue"
                : "cyan"
          }
        >
          {t(`trajectory.kinds.${node.kind}`, { defaultValue: node.kind })}
        </Tag>
        <Tag>
          {t(`trajectory.businessStatus.${node.status}`, {
            defaultValue: node.status,
          })}
        </Tag>
      </header>
      <div className="trajectory-node-id">
        Trace ID: <code>{node.display_trace_id}</code>
      </div>
      <div className="trajectory-node-times">
        <span>
          {t("trajectory.started")}: {formatTraceTime(node.started_at)}
        </span>
        <span>
          {t("trajectory.finished")}: {formatTraceTime(node.finished_at)}
        </span>
      </div>
      <div className="trajectory-node-metrics">
        {metrics.map(([label, value]) => (
          <div key={label}>
            <small>{label}</small>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      {node.usage && !node.usage.complete && (
        <p className="text-xs text-amber-700">
          {t("trajectory.partialUsage")}
          {known &&
            ` · ${t("trajectory.knownTokens")}: ${formatMetric(known.total, 0)}`}
        </p>
      )}
      {node.kind !== "tool" &&
        input != null &&
        output != null &&
        input + output > 0 && (
          <div className="trajectory-token-bar" title={`${input} / ${output}`}>
            <span style={{ width: `${(input / (input + output)) * 100}%` }} />
            <span />
          </div>
        )}
      {node.kind === "model" && node.ttft_ms != null && node.started_at && (
        <p className="text-xs text-gray-500">
          {t("trajectory.firstTokenAt")}:{" "}
          {formatTraceTime(
            new Date(Date.parse(node.started_at) + node.ttft_ms).toISOString()
          )}
        </p>
      )}
      <section>
        <button
          className="trajectory-section-title"
          aria-expanded={info}
          onClick={() => setInfo((value) => !value)}
        >
          {info ? "▾" : "▸"} {t("trajectory.executionInfo")}
        </button>
        {info && (
          <dl className="trajectory-info">
            <dt>{t("trajectory.users")}</dt>
            <dd>{node.user || node.user_id || "—"}</dd>
            <dt>{t("trajectory.models")}</dt>
            <dd>{node.model || "—"}</dd>
            <dt>{t("trajectory.directCalls")}</dt>
            <dd>{formatMetric(node.direct_child_count, 0)}</dd>
            <dt>{t("trajectory.parent")}</dt>
            <dd>
              {node.parent_id ? (
                <button
                  className="trajectory-link break-all"
                  onClick={() => onParent(node.parent_id!)}
                >
                  {node.parent_id}
                </button>
              ) : (
                "—"
              )}
            </dd>
            {Object.entries(node.attributes).map(([key, value]) => (
              <div className="contents" key={key}>
                <dt>{key}</dt>
                <dd>
                  {typeof value === "object"
                    ? JSON.stringify(value)
                    : String(value)}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </section>
      {(["input", "reasoning", "output"] as const).map((slot) => (
        <TrajectoryBody
          key={`${node.id}:${slot}`}
          reference={node[slot]}
          slot={slot}
          conversationId={conversationId}
          nodeId={node.id}
          cache={cache}
          onLoaded={onLoaded}
          onInvalidated={onInvalidated}
        />
      ))}
    </div>
  );
}
