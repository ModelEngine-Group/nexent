"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { Card, Button, Skeleton, Flex } from "antd";
import { AlertTriangle } from "lucide-react";

import { useCapacityCoverage } from "@/hooks/model/useCapacityCoverage";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { canManageModels } from "@/lib/auth";

interface Props {
  onViewAll?: () => void;
}

export default function ModelCapacityCoverageWidget({ onViewAll }: Props) {
  const { t } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const { isSpeedMode } = useDeployment();
  const visibleToOperator = canManageModels(user?.role, isSpeedMode);

  const { coverage, isLoading } = useCapacityCoverage({
    enabled: visibleToOperator,
  });

  if (!visibleToOperator) return null;
  if (isLoading) {
    return (
      <Card size="small" className="mb-3">
        <Skeleton active paragraph={{ rows: 1 }} title={false} />
      </Card>
    );
  }
  if (!coverage || coverage.bareCount === 0) return null;

  return (
    <Card
      size="small"
      className="mb-3 border-yellow-200"
      styles={{ body: { padding: "12px 16px" } }}
    >
      <Flex align="center" justify="space-between" gap={12} wrap="wrap">
        <Flex align="center" gap={10} className="min-w-0 flex-1">
          <AlertTriangle className="h-5 w-5 text-yellow-600 shrink-0" />
          <Flex vertical gap={2} className="min-w-0">
            <span className="text-sm font-medium text-gray-800">
              {t("dashboard.capacityCoverage.title")}
            </span>
            <span className="text-xs text-gray-600">
              {t("dashboard.capacityCoverage.subtitle", {
                bareCount: coverage.bareCount,
                total: coverage.totalLlmVlm,
              })}
            </span>
          </Flex>
        </Flex>
        {onViewAll && (
          <Button size="small" type="link" onClick={onViewAll}>
            {t("dashboard.capacityCoverage.viewAll")}
          </Button>
        )}
      </Flex>
    </Card>
  );
}
