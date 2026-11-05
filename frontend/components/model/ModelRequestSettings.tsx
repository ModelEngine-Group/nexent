// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Collapse, Form, type CollapseProps } from "antd";
import { Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { RequestParametersEditor } from "./RequestParametersEditor";
import { ModelHttpConnectionSettings } from "./ModelHttpConnectionSettings";

/** Shared request settings for new and saved outlets. */
export function ModelRequestSettings({
  sslVerify,
  onSslVerifyChange,
  timeout,
  onTimeoutChange,
  extras,
  onExtrasChange,
  onValidityChange,
  pending,
  showConnection = true,
  headers,
  onHeadersChange,
  onHeadersValidityChange,
  ...collapse
}: Pick<CollapseProps, "activeKey" | "onChange"> & {
  sslVerify: boolean;
  onSslVerifyChange: (verify: boolean) => void;
  timeout: number;
  onTimeoutChange: (value: number) => void;
  extras: string;
  onExtrasChange: (value: string) => void;
  onValidityChange: (valid: boolean) => void;
  pending: boolean;
  showConnection?: boolean;
  headers?: Record<string, string | null>;
  onHeadersChange?: (value: Record<string, string | null>) => void;
  onHeadersValidityChange?: (valid: boolean) => void;
}) {
  const { t } = useTranslation();
  return (
    <Collapse
      {...collapse}
      ghost
      expandIconPlacement="end"
      className="border-t text-foreground [&_.ant-collapse-header]:!bg-transparent [&_.ant-collapse-header]:!px-0 [&_.ant-collapse-header]:!py-3 [&_.ant-collapse-header]:!shadow-none [&_.ant-collapse-body]:!px-0 [&_.ant-collapse-body]:!pt-0 [&_.ant-collapse-body]:!pb-0"
      items={[
        {
          key: "advanced",
          label: (
            <span className="flex items-center gap-2 text-xs text-foreground">
              <Settings2 size={14} />
              {t(
                showConnection
                  ? "modelProfile.advanced"
                  : "modelProfile.extraParameters"
              )}
              {showConnection && (
                <span className="text-muted-foreground">
                  {t("modelProfile.layout.advancedHint")}
                </span>
              )}
            </span>
          ),
          children: (
            <section
              aria-label={t("modelProfile.requestGroup")}
              className="space-y-2"
            >
              {showConnection && (
                <>
                  <h5 className="mb-2 text-xs font-medium text-muted-foreground">
                    {t("modelProfile.httpGroup")}
                  </h5>
                  <ModelHttpConnectionSettings
                    sslVerify={sslVerify}
                    onSslVerifyChange={onSslVerifyChange}
                    timeout={timeout}
                    onTimeoutChange={onTimeoutChange}
                    headers={headers}
                    onHeadersChange={onHeadersChange}
                    onValidityChange={onHeadersValidityChange}
                    pending={pending}
                  />
                </>
              )}
              {showConnection && (
                <h5 className="text-xs font-medium text-foreground">
                  {t("modelProfile.extraParameters")}
                </h5>
              )}
              <p className="text-xs text-muted-foreground">
                {t("modelProfile.extraParametersHint")}
              </p>
              <Form.Item className="!mb-0">
                <RequestParametersEditor
                  value={extras}
                  onChange={onExtrasChange}
                  onValidityChange={onValidityChange}
                  disabled={pending}
                />
              </Form.Item>
            </section>
          ),
        },
      ]}
    />
  );
}
