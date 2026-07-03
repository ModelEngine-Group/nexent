"use client";

import { Flex, Typography } from "antd";

const { Text } = Typography;

interface MetricCardProps {
  label: string;
  value: string | number;
  highlight?: boolean;
}

export default function MetricCard({ label, value, highlight }: MetricCardProps) {
  return (
    <Flex
      vertical
      align="center"
      justify="center"
      className={`flex-1 px-4 py-3 rounded-lg border ${
        highlight
          ? "bg-blue-50 dark:bg-blue-900/30 border-blue-200 dark:border-blue-800"
          : "bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700"
      }`}
    >
      <Text className={`text-xs ${highlight ? "text-blue-600 dark:text-blue-400" : "text-slate-500 dark:text-slate-400"}`}>
        {label}
      </Text>
      <Text
        className={`text-2xl font-semibold mt-1 ${
          highlight ? "text-blue-600 dark:text-blue-400" : "text-slate-900 dark:text-white"
        }`}
      >
        {value}
      </Text>
    </Flex>
  );
}
