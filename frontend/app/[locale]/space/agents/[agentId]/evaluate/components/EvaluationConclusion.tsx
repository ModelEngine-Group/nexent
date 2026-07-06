"use client";

import { Typography } from "antd";
import { useTranslation } from "react-i18next";

const { Text } = Typography;

interface EvaluationConclusionProps {
  passRate: number;
}

function getConclusion(passRate: number): "excellent" | "medium" | "poor" {
  if (passRate >= 80) return "excellent";
  if (passRate >= 50) return "medium";
  return "poor";
}

export default function EvaluationConclusion({ passRate }: EvaluationConclusionProps) {
  const { t } = useTranslation("common");
  const key = getConclusion(passRate);
  return (
    <div className="mt-4 p-4 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
      <Text className="text-sm font-medium text-slate-600 dark:text-slate-400 block mb-1">
        {t("agentEvaluation.report.conclusionTitle")}
      </Text>
      <Text className="text-sm text-slate-700 dark:text-slate-300">
        {t(`agentEvaluation.report.conclusion.${key}`)}
      </Text>
    </div>
  );
}
