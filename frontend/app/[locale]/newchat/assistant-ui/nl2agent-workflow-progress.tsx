// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import type { CSSProperties } from "react";
import { Steps, Tag, Spin, theme } from "antd";
import { Check, ChevronRight, Minus } from "lucide-react";
import { useAuiState } from "@assistant-ui/react";
import { useTranslation } from "react-i18next";
import { useNl2AgentFlowPhase } from "@/contexts/nl2AgentFlow";
import type { Nl2AgentWorkflowView } from "@/types/nl2AgentWorkflow";
import {
  isFullGenerationTurn,
  projectNl2AgentWorkflow,
} from "./nl2agent-workflow-state";
import styles from "./nl2agent-workflow-progress.module.css";

const stepNames = ["requirements", "coverage", "binding", "generation"];

interface Nl2AgentWorkflowProgressProps {
  value: Nl2AgentWorkflowView;
}

export function Nl2AgentWorkflowProgress({
  value,
}: Nl2AgentWorkflowProgressProps) {
  const { t } = useTranslation("common");
  const { token } = theme.useToken();
  const labels = stepNames.map((name) => t(`nl2agent.workflow.step.${name}`));
  const complete = value.status === "completed";
  const detail = t(`nl2agent.workflow.detail.${value.detail}`);
  const matching = value.current === 1 && value.mode;
  return (
    <section
      className={styles.root}
      data-testid="nl2agent-workflow-progress"
      data-step={stepNames[value.current]}
      data-state={value.status}
      aria-label={t("nl2agent.workflow.label")}
      style={
        {
          "--workflow-primary": token.colorPrimary,
          "--workflow-success": token.colorSuccess,
          "--workflow-muted": token.colorTextTertiary,
          "--workflow-text": token.colorText,
          "--workflow-border": token.colorBorderSecondary,
          "--workflow-bg": token.colorBgContainer,
          "--workflow-subtle": token.colorFillAlter,
          "--workflow-white": token.colorWhite,
          "--workflow-radius": `${token.borderRadiusLG}px`,
          "--workflow-shadow": token.boxShadowTertiary,
        } as CSSProperties
      }
    >
      <div className={styles.steps}>
        <Steps
          size="small"
          current={value.current}
          responsive={false}
          styles={{
            itemTitle: { fontSize: 12 },
            itemContent: { fontSize: 12 },
          }}
          status={
            value.status === "error" ? "error" : complete ? "finish" : "process"
          }
          items={labels.map((title, index) => ({
            title,
            status: value.skipped.includes(index)
              ? "wait"
              : index < value.current || complete
                ? "finish"
                : index === value.current
                  ? value.status === "error"
                    ? "error"
                    : "process"
                  : "wait",
            icon:
              !value.skipped.includes(index) &&
              (index < value.current || complete) ? (
                <span className={styles.finished}>
                  <Check size={13} />
                </span>
              ) : undefined,
            styles: {
              content: {
                color:
                  index === value.current
                    ? token.colorPrimary
                    : token.colorTextTertiary,
              },
            },
            content: value.skipped.includes(index)
              ? t("nl2agent.workflow.skipped")
              : undefined,
          }))}
        />
      </div>
      <div className={styles.compact} aria-label={labels.join(" → ")}>
        <span>
          {t("nl2agent.workflow.position", {
            current: value.current + 1,
            total: 4,
          })}{" "}
          · {labels[value.current]}
        </span>
      </div>
      <div className={styles.details} role="status" aria-live="polite">
        {matching && (
          <Tag className={styles.mode}>
            {t(`nl2agent.workflow.mode.${value.mode}`)}
          </Tag>
        )}
        {matching && value.status !== "running" && (
          <span className={styles.muted}>{detail}</span>
        )}
        {matching ? (
          <div className={styles.pipeline}>
            {value.pipeline.map((status, index) => (
              <span className={styles.pipelineItem} key={index}>
                {index > 0 && (
                  <ChevronRight
                    size={12}
                    className={styles.muted}
                    aria-hidden
                  />
                )}
                {status === "done" ? (
                  <Check size={13} className={styles.check} aria-hidden />
                ) : status === "skipped" ? (
                  <Minus size={13} className={styles.muted} aria-hidden />
                ) : status === "running" && value.status === "running" ? (
                  <span data-testid="nl2agent-workflow-spinner">
                    <Spin size="small" />
                  </span>
                ) : null}
                <span
                  className={
                    status === "pending" || status === "skipped"
                      ? styles.muted
                      : undefined
                  }
                >
                  {t(
                    `nl2agent.workflow.pipeline.${index}.${status === "running" && value.status !== "running" ? "pending" : status}`
                  )}
                  {status === "running" &&
                  value.status === "running" &&
                  value.counts
                    ? ` (${value.counts.completed}/${value.counts.total})`
                    : ""}
                </span>
              </span>
            ))}
          </div>
        ) : (
          <span className={styles.muted}>{detail}</span>
        )}
        {matching && value.fallback && (
          <span className={styles.fallback}>
            {t("nl2agent.workflow.fallback")}
          </span>
        )}
      </div>
    </section>
  );
}

export function Nl2AgentWorkflowHeader({
  agentId,
  restoring,
}: {
  agentId: number | null;
  restoring: boolean;
}) {
  const messages = useAuiState((state) => state.thread.messages);
  const isRunning = useAuiState((state) => state.thread.isRunning);
  const phase = useNl2AgentFlowPhase(agentId);
  const value = projectNl2AgentWorkflow({
    agentId,
    messages: restoring ? [] : messages,
    isRunning,
    phase: restoring ? "idle" : phase,
  });
  if (
    restoring ||
    !isFullGenerationTurn(messages, agentId) ||
    (!isRunning && messages.length === 0)
  )
    return null;
  return <Nl2AgentWorkflowProgress value={value} />;
}
