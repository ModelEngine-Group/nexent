// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useRef, useState } from "react";
import { Tag } from "antd";
import { ChevronDown, ChevronRight, GitBranch } from "lucide-react";
import { useTranslation } from "react-i18next";
import { BodyCache, formatMetric } from "@/lib/trajectory";
import type { TrajectoryNode } from "@/types/trajectory";
import { TrajectoryBody } from "./TrajectoryBody";
import { AgentVersion } from "./AgentVersion";
import {
  CopyTraceId,
  NodeIcon,
  TrajectoryStatus,
  nodeDuration,
  nodeTime,
} from "./TrajectoryPresentation";

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
    [t("trajectory.duration"), nodeDuration(node.duration_ms)],
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
      <header className="trajectory-node-heading">
        <div className="trajectory-node-title">
          <NodeIcon kind={node.kind} large />
          <div className="min-w-0 flex-1">
            <div className="trajectory-node-title-row">
              <h2>{node.name}</h2>
              {node.round_no != null && (
                <span className="trajectory-round-label">
                  {t("trajectory.round", { number: node.round_no })}
                </span>
              )}
              <Tag>
                {t(`trajectory.kinds.${node.kind}`, {
                  defaultValue: node.kind,
                })}
              </Tag>
            </div>
            <div className="trajectory-node-id">
              <span>Trace ID</span>
              <code title={node.display_trace_id}>{node.display_trace_id}</code>
              <CopyTraceId value={node.display_trace_id} />
              {node.parent_id ? (
                <button
                  className="trajectory-parent-link"
                  onClick={() => onParent(node.parent_id!)}
                >
                  <GitBranch size={12} />
                  {t("trajectory.parent")}
                </button>
              ) : (
                <span className="trajectory-root-label">
                  {t("trajectory.rootNode")}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="trajectory-node-times">
          <TrajectoryStatus status={node.status} />
          <span>
            {t("trajectory.started")} <time>{nodeTime(node.started_at)}</time>
          </span>
          <span>
            {t("trajectory.finished")} <time>{nodeTime(node.finished_at)}</time>
          </span>
        </div>
      </header>
      <section className="trajectory-node-summary">
        <div className="trajectory-node-metrics" data-kind={node.kind}>
          {metrics.map(([label, value]) => (
            <div
              key={label}
              title={
                label === t("trajectory.ttft") &&
                node.ttft_ms != null &&
                node.started_at
                  ? `${t("trajectory.firstTokenAt")}: ${nodeTime(new Date(Date.parse(node.started_at) + node.ttft_ms).toISOString())}`
                  : undefined
              }
            >
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
            <div
              className="trajectory-token-bar"
              title={`${input} / ${output}`}
            >
              <span style={{ width: `${(input / (input + output)) * 100}%` }} />
              <span />
            </div>
          )}
      </section>
      <section className="trajectory-execution-info">
        <button
          className="trajectory-section-title"
          aria-expanded={info}
          onClick={() => setInfo((value) => !value)}
        >
          {info ? <ChevronDown size={12} /> : <ChevronRight size={12} />}{" "}
          {t("trajectory.executionInfo")}
        </button>
        {info && (
          <dl className="trajectory-info">
            <div>
              <dt>{t("trajectory.users")}</dt>
              <dd>{node.user || node.user_id || "—"}</dd>
            </div>
            {node.kind === "agent" && (
              <div>
                <dt>{t("trajectory.agentVersion")}</dt>
                <dd>
                  <AgentVersion
                    version={node.agent_version_no}
                    name={node.agent_version_name}
                  />
                </dd>
              </div>
            )}
            {node.kind === "agent" && node.agent_version_name && (
              <div>
                <dt>{t("trajectory.versionName")}</dt>
                <dd>{node.agent_version_name || "—"}</dd>
              </div>
            )}
            <div>
              <dt>{t("trajectory.models")}</dt>
              <dd title={node.model || undefined}>{node.model || "—"}</dd>
            </div>
            <div>
              <dt>TraceID</dt>
              <dd title={node.display_trace_id}>{node.display_trace_id}</dd>
            </div>
            <div>
              <dt>{t("trajectory.directCalls")}</dt>
              <dd>{formatMetric(node.direct_child_count, 0)}</dd>
            </div>
            {Object.entries(node.attributes).map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd
                  title={
                    typeof value === "object"
                      ? JSON.stringify(value)
                      : String(value)
                  }
                >
                  {typeof value === "object"
                    ? JSON.stringify(value)
                    : String(value)}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </section>
      {(["input", "reasoning", "output"] as const)
        .filter(
          (slot) =>
            slot !== "reasoning" ||
            node.kind === "model" ||
            node.reasoning.availability !== "not_returned"
        )
        .map((slot) => (
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
