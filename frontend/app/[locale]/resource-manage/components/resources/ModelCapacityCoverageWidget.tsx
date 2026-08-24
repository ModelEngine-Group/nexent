"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  Card,
  Descriptions,
  Flex,
  message,
  Modal,
  Skeleton,
  Table,
  Tag,
} from "antd";
import { Activity, ShieldCheck } from "lucide-react";
import { useCapacityHealth } from "@/hooks/model/useCapacityHealth";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useQuery } from "@tanstack/react-query";
import { canManageModels } from "@/lib/auth";
import { modelService } from "@/services/modelService";
import type {
  CapacityAdoptionPreview,
  CapacityHealthItem,
  CapacityHealthStatus,
} from "@/types/modelConfig";

const COLORS: Record<CapacityHealthStatus, string> = {
  healthy: "green",
  review_due: "gold",
  expired: "red",
  estimated: "orange",
  unconfigured: "red",
  invalid: "red",
  probe_degraded: "volcano",
};

export default function ModelCapacityCoverageWidget() {
  const { t } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const { isSpeedMode } = useDeployment();
  const visible = canManageModels(user?.role, isSpeedMode);
  const { health, isLoading, invalidate } = useCapacityHealth({
    enabled: visible,
  });
  const { data: catalogStatus } = useQuery({
    queryKey: ["modelCapacityCatalogStatus"],
    queryFn: modelService.getCapacityCatalogStatus,
    staleTime: 60_000,
    enabled: visible,
  });
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<CapacityHealthItem | null>(null);
  const [preview, setPreview] = useState<CapacityAdoptionPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const unhealthy = useMemo(
    () => health?.items.filter((item) => item.status !== "healthy") || [],
    [health]
  );
  if (!visible) return null;
  if (isLoading)
    return (
      <Card size="small" className="mb-3">
        <Skeleton active paragraph={{ rows: 1 }} title={false} />
      </Card>
    );
  if (!health) return null;

  const review = async (item: CapacityHealthItem) => {
    setSelected(item);
    setPreview(null);
    setOpen(true);
    if (!item.suggestionAvailable) return;
    setBusy(true);
    try {
      setPreview(
        await modelService.previewCapacityAdoption(
          item.displayName,
          item.matcherVersion
        )
      );
    } catch (error: unknown) {
      message.error(
        (error instanceof Error ? error.message : "") ||
          t("modelConfig.capacityHealth.previewFailed")
      );
    } finally {
      setBusy(false);
    }
  };
  const adopt = async () => {
    if (
      !selected ||
      !preview ||
      !Object.values(preview.fields).some((field) => field.applicable)
    )
      return;
    setBusy(true);
    try {
      await modelService.adoptCapacity({
        displayName: selected.displayName,
        expectedProfileVersion: preview.proposedProfileVersion,
        expectedMatcherVersion: preview.matcherVersion,
      });
      message.success(t("modelConfig.capacityHealth.applied"));
      setOpen(false);
      await invalidate();
    } catch (error: unknown) {
      message.error(
        (error instanceof Error ? error.message : "") ||
          t("modelConfig.capacityHealth.applyFailed")
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Card
        size="small"
        className="mb-3"
        styles={{ body: { padding: "12px 16px" } }}
      >
        <Flex align="center" justify="space-between" gap={12} wrap="wrap">
          <Flex align="center" gap={10}>
            {unhealthy.length ? (
              <Activity className="h-5 w-5 text-orange-600" />
            ) : (
              <ShieldCheck className="h-5 w-5 text-green-600" />
            )}
            <div>
              <div className="text-sm font-medium">
                {t("modelConfig.capacityHealth.title")}
              </div>
              <div className="text-xs text-gray-600">
                {t("modelConfig.capacityHealth.summary", {
                  healthy: health.counts.healthy || 0,
                  total: health.total,
                  revision: health.catalogRevision,
                })}
              </div>
              {catalogStatus && (
                <div className="text-xs text-gray-500 mt-0.5">
                  {t("modelConfig.capacityHealth.catalogLifecycle", {
                    current: catalogStatus.lifecycleCounts.current || 0,
                    reviewDue: catalogStatus.lifecycleCounts.review_due || 0,
                    expired: catalogStatus.lifecycleCounts.expired || 0,
                  })}
                  {catalogStatus.candidate && (
                    <Tag color="blue" className="ml-2">
                      {t("modelConfig.capacityHealth.catalogCandidate", {
                        revision: catalogStatus.candidate.revision,
                        added: catalogStatus.candidate.added.length,
                        changed: catalogStatus.candidate.changed.length,
                        removed: catalogStatus.candidate.removed.length,
                      })}
                    </Tag>
                  )}
                </div>
              )}
            </div>
          </Flex>
          {unhealthy.length > 0 && (
            <Button size="small" onClick={() => setOpen(true)}>
              {t("modelConfig.capacityHealth.review", {
                count: unhealthy.length,
              })}
            </Button>
          )}
        </Flex>
      </Card>
      <Modal
        open={open}
        width={860}
        title={t("modelConfig.capacityHealth.title")}
        onCancel={() => setOpen(false)}
        okText={t("modelConfig.capacityHealth.applyReviewed")}
        okButtonProps={{
          disabled:
            !preview ||
            !Object.values(preview.fields).some((field) => field.applicable),
        }}
        confirmLoading={busy}
        onOk={adopt}
      >
        <Table
          size="small"
          pagination={false}
          rowKey="modelId"
          dataSource={unhealthy}
          columns={[
            {
              title: t("modelConfig.capacityHealth.model"),
              dataIndex: "displayName",
            },
            {
              title: t("modelConfig.capacityHealth.status"),
              dataIndex: "status",
              filters: Array.from(
                new Set(unhealthy.map((item) => item.status))
              ).map((status) => ({
                text: t(`modelConfig.capacityHealth.statuses.${status}`),
                value: status,
              })),
              onFilter: (value, item) => item.status === value,
              render: (value: CapacityHealthStatus) => (
                <Tag color={COLORS[value]}>
                  {t(`modelConfig.capacityHealth.statuses.${value}`)}
                </Tag>
              ),
            },
            {
              title: t("modelConfig.capacityHealth.reason"),
              dataIndex: "reasons",
              render: (values: string[]) =>
                values
                  .map((value) =>
                    t(`modelConfig.capacityHealth.reasons.${value}`)
                  )
                  .join(", "),
            },
            {
              title: t("modelConfig.capacityHealth.action"),
              render: (_: unknown, item: CapacityHealthItem) => (
                <Button
                  size="small"
                  disabled={!item.suggestionAvailable}
                  onClick={() => review(item)}
                >
                  {t("modelConfig.capacityHealth.reviewFix")}
                </Button>
              ),
            },
          ]}
        />
        {selected && (
          <Descriptions
            size="small"
            column={2}
            className="mt-4"
            bordered
            title={selected.displayName}
            items={[
              {
                key: "profile",
                label: t("modelConfig.capacityHealth.profile"),
                children:
                  preview?.proposedProfileVersion ||
                  selected.profileVersion ||
                  "—",
              },
              {
                key: "verified",
                label: t("modelConfig.capacityHealth.verifiedAt"),
                children: selected.verifiedAt || "—",
              },
            ]}
          />
        )}
        {preview && (
          <Table
            className="mt-3"
            size="small"
            pagination={false}
            rowKey="field"
            dataSource={Object.entries(preview.fields).map(([field, diff]) => ({
              field,
              ...diff,
            }))}
            columns={[
              {
                title: t("modelConfig.capacityHealth.field"),
                dataIndex: "field",
              },
              {
                title: t("modelConfig.capacityHealth.current"),
                dataIndex: "currentValue",
                render: (v) => String(v ?? "—"),
              },
              {
                title: t("modelConfig.capacityHealth.proposed"),
                dataIndex: "proposedValue",
                render: (v) => String(v ?? "—"),
              },
              {
                title: t("modelConfig.capacityHealth.protection"),
                render: (_: unknown, item) =>
                  item.blockedByManual ? (
                    <Tag color="blue">
                      {t("modelConfig.capacityHealth.manualProtected")}
                    </Tag>
                  ) : item.applicable ? (
                    <Tag>{t("modelConfig.capacityHealth.applicable")}</Tag>
                  ) : (
                    <Tag>{t("modelConfig.capacityHealth.noChange")}</Tag>
                  ),
              },
            ]}
          />
        )}
      </Modal>
    </>
  );
}
