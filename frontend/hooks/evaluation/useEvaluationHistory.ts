"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { message } from "antd";
import { evaluationService } from "@/services/evaluationService";
import { useTranslation } from "react-i18next";
import type { EvaluationHistoryItem, AgentEvaluationRun } from "@/types/agentEvaluation";

const POLL_INTERVAL_MS = 2000;

export function useEvaluationHistory(agentId: number, onCompleted?: (item: EvaluationHistoryItem) => void) {
  const { t } = useTranslation("common");
  const [history, setHistory] = useState<EvaluationHistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const historyRef = useRef(history);
  historyRef.current = history;
  const onCompletedRef = useRef(onCompleted);
  onCompletedRef.current = onCompleted;

  const toHistoryItem = (run: AgentEvaluationRun): EvaluationHistoryItem => ({
    agent_evaluation_id: run.agent_evaluation_id,
    agent_version_no: run.agent_version_no,
    evaluation_set_name: run.evaluation_set_name,
    judge_model_name: run.judge_model_name,
    status: run.status,
    score_overall: run.score_overall,
    pass_count: run.pass_count,
    fail_count: run.fail_count,
    progress_total: run.progress_total,
    progress_done: run.progress_done,
    create_time: run.create_time,
  });

  const fetchRuns = useCallback(async () => {
    return evaluationService.listAgentEvaluationsByAgent(agentId, { limit: 100, offset: 0 });
  }, [agentId]);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchRuns()
      .then((runs) => setHistory(runs.map(toHistoryItem)))
      .catch(() => message.error(t("agentEvaluation.message.loadRunsFailed")))
      .finally(() => setLoading(false));
    return () => stopPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId]);

  useEffect(() => {
    const hasRunning = historyRef.current.some(
      (r) => r.status === "PENDING" || r.status === "RUNNING"
    );
    if (hasRunning && !pollingRef.current) {
      pollingRef.current = setInterval(async () => {
        try {
          const runs = await fetchRuns();
          const updated = runs.map(toHistoryItem);
          setHistory(updated);
          const stillRunning = updated.some(
            (r) => r.status === "PENDING" || r.status === "RUNNING"
          );
          if (!stillRunning) stopPolling();
          if (onCompletedRef.current) {
            for (const item of updated) {
              if (item.status === "COMPLETED" || item.status === "FAILED") {
                const prev = historyRef.current.find(
                  (r) => r.agent_evaluation_id === item.agent_evaluation_id
                );
                if (prev && (prev.status === "PENDING" || prev.status === "RUNNING")) {
                  onCompletedRef.current(item);
                }
              }
            }
          }
        } catch {
          // ignore poll errors
        }
      }, POLL_INTERVAL_MS);
    } else if (!hasRunning) {
      stopPolling();
    }
  }, [history, fetchRuns, stopPolling]);

  const deleteRun = useCallback(
    async (evaluationId: number) => {
      setDeletingId(evaluationId);
      try {
        await evaluationService.deleteAgentEvaluation(evaluationId);
        setHistory((prev) => prev.filter((r) => r.agent_evaluation_id !== evaluationId));
        return { success: true };
      } catch (err: any) {
        message.error(err?.message || t("agentEvaluation.message.deleteRunFailed"));
        return { success: false };
      } finally {
        setDeletingId(null);
      }
    },
    [t]
  );

  return { history, loading, deletingId, loadHistory: fetchRuns, deleteRun };
}
