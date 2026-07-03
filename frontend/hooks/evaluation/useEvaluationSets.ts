"use client";

import { useCallback, useState } from "react";
import { message } from "antd";
import { evaluationService } from "@/services/evaluationService";
import { useTranslation } from "react-i18next";
import type { EvaluationSet } from "@/types/agentEvaluation";

export function useEvaluationSets() {
  const { t } = useTranslation("common");
  const [sets, setSets] = useState<EvaluationSet[]>([]);
  const [loading, setLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const loadSets = useCallback(async () => {
    setLoading(true);
    try {
      const data = await evaluationService.listEvaluationSets({ limit: 200, offset: 0 });
      setSets(data || []);
    } catch {
      message.error(t("agentEvaluation.message.loadSetsFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  const deleteSet = useCallback(
    async (setId: number) => {
      setDeletingId(setId);
      try {
        await evaluationService.deleteEvaluationSet(setId);
        setSets((prev) => prev.filter((s) => s.evaluation_set_id !== setId));
        return { success: true };
      } catch (err: any) {
        const msg = err?.message || "";
        if (
          msg.includes("referenced") ||
          msg.includes("引用") ||
          msg.includes("used") ||
          msg.includes("400")
        ) {
          message.error(t("agentEvaluation.lib.deleteReferenced", { n: 1 }));
        } else {
          message.error(msg || t("agentEvaluation.message.deleteSetFailed"));
        }
        return { success: false, error: msg };
      } finally {
        setDeletingId(null);
      }
    },
    [t]
  );

  return { sets, loading, deletingId, loadSets, deleteSet };
}
