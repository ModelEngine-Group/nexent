"use client";

import { useCallback, useState } from "react";
import { message } from "antd";
import { evaluationService } from "@/services/evaluationService";
import { useTranslation } from "react-i18next";

export function useEvaluationReport() {
  const { t } = useTranslation("common");
  const [exporting, setExporting] = useState(false);

  const exportReport = useCallback(
    async (evaluationId: number) => {
      setExporting(true);
      try {
        const blob = await evaluationService.downloadEvaluationReport(evaluationId);
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `evaluation-report-${evaluationId}.xlsx`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (err: any) {
        message.error(err?.message || t("agentEvaluation.message.exportFailed"));
      } finally {
        setExporting(false);
      }
    },
    [t]
  );

  return { exportReport, exporting };
}
