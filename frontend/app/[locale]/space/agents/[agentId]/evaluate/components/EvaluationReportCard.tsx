"use client";

import { Button, Flex, Spin, Typography } from "antd";
import { Download } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useEvaluationReport } from "@/hooks/evaluation/useEvaluationReport";
import MetricCard from "./MetricCard";
import ResultDistributionBar from "./ResultDistributionBar";
import EvaluationConclusion from "./EvaluationConclusion";
import type { EvaluationHistoryItem } from "@/types/agentEvaluation";

const { Text } = Typography;

interface EvaluationReportCardProps {
  run: EvaluationHistoryItem | null;
  loading?: boolean;
}

export default function EvaluationReportCard({ run, loading }: EvaluationReportCardProps) {
  const { t } = useTranslation("common");
  const { exportReport, exporting } = useEvaluationReport();

  if (loading) {
    return (
      <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden bg-white dark:bg-slate-900">
        <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
          <Flex align="center" gap={2}>
            <div className="w-6 h-6 rounded-full bg-blue-500 flex items-center justify-center flex-shrink-0">
              <Text className="text-xs font-semibold text-white leading-none">2</Text>
            </div>
            <Text className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              {t("agentEvaluation.report.title")}
            </Text>
          </Flex>
        </div>
        <Flex align="center" justify="center" className="py-12">
          <Spin />
        </Flex>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden bg-white dark:bg-slate-900">
        <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
          <Flex align="center" gap={2}>
            <div className="w-6 h-6 rounded-full bg-blue-500 flex items-center justify-center flex-shrink-0">
              <Text className="text-xs font-semibold text-white leading-none">2</Text>
            </div>
            <Text className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              {t("agentEvaluation.report.title")}
            </Text>
          </Flex>
        </div>
        <Flex align="center" justify="center" className="py-12">
          <Text type="secondary" className="text-sm">
            {t("agentEvaluation.report.empty", "请选择一条测评历史查看报告")}
          </Text>
        </Flex>
      </div>
    );
  }

  const passCount = run.pass_count ?? 0;
  const failCount = run.fail_count ?? 0;
  const total = passCount + failCount;
  const passRate = total > 0 ? Math.round((passCount / total) * 100) : 0;
  const score = run.score_overall != null ? run.score_overall.toFixed(1) : "-";

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden bg-white dark:bg-slate-900">
      {/* Header with number circle */}
      <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
        <Flex align="center" justify="space-between">
          <Flex align="center" gap={2}>
            <div className="w-6 h-6 rounded-full bg-blue-500 flex items-center justify-center flex-shrink-0">
              <Text className="text-xs font-semibold text-white leading-none">2</Text>
            </div>
            <Text className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              {t("agentEvaluation.report.title")}
            </Text>
          </Flex>
          <Button
            size="small"
            variant="outline"
            icon={<Download className="w-3.5 h-3.5" />}
            loading={exporting}
            onClick={() => exportReport(run.agent_evaluation_id)}
            className="text-xs"
          >
            {t("agentEvaluation.report.export")}
          </Button>
        </Flex>
      </div>

      {/* Content */}
      <div className="px-4 py-4">
        <Flex vertical gap={5}>
          {/* Metrics row */}
          <Flex gap={3} justify="stretch" wrap>
            <MetricCard label={t("agentEvaluation.report.metric.passRate")} value={`${passRate}%`} highlight />
            <MetricCard label={t("agentEvaluation.report.metric.avgScore")} value={score} />
            <MetricCard label={t("agentEvaluation.report.metric.caseCount")} value={total} />
          </Flex>

          {/* Distribution bar */}
          <ResultDistributionBar passCount={passCount} failCount={failCount} />

          {/* Conclusion */}
          <EvaluationConclusion passRate={passRate} />
        </Flex>
      </div>
    </div>
  );
}
