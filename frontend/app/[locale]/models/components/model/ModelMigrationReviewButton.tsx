// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, App, Descriptions, Modal } from "antd";
import { useTranslation } from "react-i18next";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { StandardButton } from "@/components/common/StandardButton";
import {
  confirmModelOutletMigration,
  getModelOutlet,
} from "@/services/modelProfileService";
import type { ModelOption } from "@/types/modelConfig";

function object(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function ModelMigrationReviewButton({
  model,
  onReviewed,
}: {
  model: ModelOption;
  onReviewed?: () => void;
}) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { user } = useAuthorizationContext();
  const [open, setOpen] = useState(false);
  const admin = user?.role === "SU" || user?.role === "ADMIN";
  const outlet = useQuery({
    queryKey: ["model-outlet-review", model.id],
    queryFn: ({ signal }) => getModelOutlet(model.id, signal),
    enabled: open && admin && model.migrationStatus === "migrated",
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: Infinity,
  });
  const confirm = useMutation({
    mutationFn: async () => {
      if (!outlet.data) throw new Error("Missing displayed outlet revision");
      await confirmModelOutletMigration(model.id, outlet.data.config_revision);
    },
    onSuccess: () => {
      setOpen(false);
      onReviewed?.();
      message.success(t("modelMigration.confirmed"));
    },
    onError: () => {
      message.error(t("modelMigration.confirmFailed"));
    },
  });
  if (!admin || !model.migrationStatus) return null;
  const profile = object(outlet.data?.profile);
  const identity = object(profile.identity);
  const connection = object(profile.connection);
  const capabilities = object(profile.capabilities);
  const context = object(capabilities.context);
  const printable = (value: unknown) =>
    value === undefined || value === null
      ? t("modelMigration.unknown")
      : JSON.stringify(value);
  return (
    <>
      <StandardButton
        onClick={() => {
          setOpen(true);
          if (model.migrationStatus === "migrated") void outlet.refetch();
        }}
      >
        {t("modelMigration.review")}
      </StandardButton>
      <Modal
        open={open}
        centered
        title={t("modelMigration.reviewTitle")}
        onCancel={() => !confirm.isPending && setOpen(false)}
        footer={
          model.migrationStatus === "migrated" ? (
            <StandardButton
              variant="primary"
              loading={confirm.isPending}
              disabled={!outlet.data || outlet.isFetching || outlet.isError}
              onClick={() => confirm.mutate()}
            >
              {t("modelMigration.confirm")}
            </StandardButton>
          ) : null
        }
      >
        <Alert
          type={model.migrationStatus === "failed" ? "error" : "info"}
          showIcon
          title={t(
            model.migrationStatus === "failed"
              ? "modelMigration.failedHint"
              : "modelMigration.pendingHint"
          )}
        />
        {model.migrationStatus === "failed" && (
          <p>{model.migrationDiagnostic?.category}</p>
        )}
        {outlet.isFetching && (
          <p role="status">{t("modelProfile.previewLoading")}</p>
        )}
        {outlet.isError && (
          <Alert type="error" title={t("modelMigration.loadFailed")} />
        )}
        {outlet.data && (
          <Descriptions
            className="mt-4"
            column={1}
            items={[
              {
                key: "revision",
                label: t("modelMigration.revision"),
                children: outlet.data.config_revision,
              },
              {
                key: "model",
                label: t("modelProfile.requestModel"),
                children: printable(identity.request_model_id),
              },
              {
                key: "endpoint",
                label: t("modelProfile.endpoint"),
                children: printable(connection.base_url),
              },
              {
                key: "window",
                label: t("modelMigration.contextWindow"),
                children: printable(context.combined_window),
              },
              {
                key: "inputLimit",
                label: t("modelMigration.inputLimit"),
                children: printable(context.input_limit),
              },
              {
                key: "outputLimit",
                label: t("modelMigration.outputLimit"),
                children: printable(context.output_limit),
              },
              {
                key: "timeout",
                label: t("modelProfile.timeout"),
                children: printable(connection.timeout_seconds),
              },
              {
                key: "ssl",
                label: t("modelProfile.sslVerify"),
                children: printable(connection.ssl_verify),
              },
              {
                key: "tools",
                label: t("modelMigration.nativeTools"),
                children: printable(object(capabilities.tools).status),
              },
              {
                key: "thinking",
                label: t("modelMigration.reasoning"),
                children: printable(object(capabilities.reasoning).status),
              },
              {
                key: "credential",
                label: t("modelProfile.apiKey"),
                children: t(
                  outlet.data.has_credential
                    ? "modelMigration.credentialPresent"
                    : "modelMigration.credentialAbsent"
                ),
              },
              {
                key: "parameters",
                label: t("modelMigration.parameters"),
                children: (
                  <pre className="whitespace-pre-wrap break-all">
                    {JSON.stringify(profile.parameter_values, null, 2)}
                  </pre>
                ),
              },
              {
                key: "extras",
                label: t("modelProfile.extraParameters"),
                children: (
                  <pre className="whitespace-pre-wrap break-all">
                    {JSON.stringify(profile.extra_api_parameters, null, 2)}
                  </pre>
                ),
              },
            ]}
          />
        )}
      </Modal>
    </>
  );
}
