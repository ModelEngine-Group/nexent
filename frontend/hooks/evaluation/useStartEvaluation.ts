"use client";

import { useCallback, useState } from "react";
import { message } from "antd";
import { evaluationService } from "@/services/evaluationService";
import { useTranslation } from "react-i18next";
import type { AgentEvaluationRun } from "@/types/agentEvaluation";

export function useStartEvaluation() {
  const { t } = useTranslation("common");
  const [starting, setStarting] = useState(false);

  const startEvaluation = useCallback(
    async (params: {
      agentId: number;
      evaluationSetId: number;
      judgeModelId: number;
    }): Promise<AgentEvaluationRun | null> => {
      setStarting(true);
      try {
        const run = await evaluationService.createAgentEvaluation({
          agent_id: params.agentId,
          evaluation_set_id: params.evaluationSetId,
          judge_model_id: params.judgeModelId,
        });
        message.success(t("agentEvaluation.message.startSuccess"));
        return run;
      } catch (err: any) {
        message.error(err?.message || t("agentEvaluation.message.startFailed"));
        return null;
      } finally {
        setStarting(false);
      }
    },
    [t]
  );

  return { startEvaluation, starting };
}
