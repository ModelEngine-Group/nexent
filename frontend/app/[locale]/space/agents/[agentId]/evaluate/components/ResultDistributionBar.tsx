"use client";

import { useTranslation } from "react-i18next";
import { Flex, Typography } from "antd";

const { Text } = Typography;

interface ResultDistributionBarProps {
  passCount: number;
  failCount: number;
}

export default function ResultDistributionBar({ passCount, failCount }: ResultDistributionBarProps) {
  const { t } = useTranslation("common");
  const total = passCount + failCount;
  const passPct = total > 0 ? Math.round((passCount / total) * 100) : 0;

  return (
    <div>
      <Text className="text-sm font-medium text-slate-700 dark:text-slate-300 block mb-3">
        {t("agentEvaluation.report.distributionTitle")}
      </Text>
      <div className="h-3 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden flex">
        {passCount > 0 && (
          <div
            className="h-full bg-green-500 transition-all duration-300"
            style={{ width: `${passPct}%` }}
          />
        )}
        {failCount > 0 && (
          <div
            className="h-full bg-red-500 transition-all duration-300"
            style={{ width: `${100 - passPct}%` }}
          />
        )}
      </div>
      <Flex gap={4} align="center" className="mt-3">
        <Flex gap={1.5} align="center">
          <div className="w-2.5 h-2.5 rounded-full bg-green-500" />
          <Text className="text-xs text-slate-500 dark:text-slate-400">
            {t("agentEvaluation.report.distPass", { n: passCount })}
          </Text>
        </Flex>
        <Text className="text-slate-300 dark:text-slate-600">|</Text>
        <Flex gap={1.5} align="center">
          <div className="w-2.5 h-2.5 rounded-full bg-red-500" />
          <Text className="text-xs text-slate-500 dark:text-slate-400">
            {t("agentEvaluation.report.distFail", { n: failCount })}
          </Text>
        </Flex>
      </Flex>
    </div>
  );
}
