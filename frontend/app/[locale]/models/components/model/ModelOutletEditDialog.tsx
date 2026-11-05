// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert, Modal, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { StandardButton } from "@/components/common/StandardButton";
import { getModelOutlet } from "@/services/modelProfileService";
import { ModelOutletAddForm } from "./ModelOutletAddForm";

interface EditProps {
  modelId: number;
  onClose: () => void;
  onSuccess: () => void;
}

export function ModelOutletEditDialog({
  modelId,
  onClose,
  onSuccess,
}: EditProps) {
  const { t } = useTranslation();
  const { user } = useAuthorizationContext();
  const outlet = useQuery({
    queryKey: ["model-outlet-edit", modelId],
    queryFn: ({ signal }) => getModelOutlet(modelId, signal),
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const migration =
    outlet.data?.profile.provenance?.provider_metadata?.migration;
  const reviewRequired =
    !!migration &&
    typeof migration === "object" &&
    (!("reviewed_revision" in migration) ||
      migration.reviewed_revision !== outlet.data?.config_revision);
  const admin = user?.role === "SU" || user?.role === "ADMIN";
  return (
    <Modal
      open
      centered
      title={t("modelProfile.edit")}
      footer={null}
      onCancel={onClose}
      destroyOnHidden
      width={1040}
      styles={{
        body: {
          padding: 0,
          display: "flex",
          flexDirection: "column",
          maxHeight: "calc(85vh - 64px)",
        },
        container: { padding: 0 },
        header: {
          margin: 0,
          padding: "20px 24px",
          borderBottom: "1px solid var(--border)",
        },
      }}
    >
      {outlet.isFetching ? (
        <Spin />
      ) : outlet.isError ? (
        <Alert
          type="error"
          title={t("modelProfile.loadFailed")}
          action={
            <StandardButton onClick={() => void outlet.refetch()}>
              {t("common.retry")}
            </StandardButton>
          }
        />
      ) : (
        outlet.data && (
          <>
            {reviewRequired && (
              <div className="border-b px-6 py-3">
                <Alert
                  type="info"
                  showIcon
                  title={t("modelMigration.pendingHint")}
                />
              </div>
            )}
            <ModelOutletAddForm
              key={`${modelId}:${outlet.data.config_revision}`}
              editing={outlet.data}
              reviewMigration={reviewRequired && admin}
              onDone={onClose}
              onPendingChange={() => undefined}
              onSuccess={onSuccess}
            />
          </>
        )
      )}
    </Modal>
  );
}
