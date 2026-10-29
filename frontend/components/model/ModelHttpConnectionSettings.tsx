// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Form, InputNumber, Switch } from "antd";
import { useTranslation } from "react-i18next";
import { HttpHeadersEditor } from "./HttpHeadersEditor";

export function ModelHttpConnectionSettings({
  sslVerify,
  onSslVerifyChange,
  timeout,
  onTimeoutChange,
  headers,
  onHeadersChange,
  onValidityChange,
  pending,
}: {
  sslVerify: boolean;
  onSslVerifyChange: (verify: boolean) => void;
  timeout: number;
  onTimeoutChange: (value: number) => void;
  headers?: Record<string, string | null>;
  onHeadersChange?: (value: Record<string, string | null>) => void;
  onValidityChange?: (valid: boolean) => void;
  pending?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <section aria-label={t("modelProfile.httpGroup")} className="space-y-3">
      <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
        <Form.Item className="!mb-0" label={t("modelProfile.skipTlsVerify")}>
          <Switch
            aria-label={t("modelProfile.skipTlsVerify")}
            checked={!sslVerify}
            disabled={pending}
            onChange={(skip) => onSslVerifyChange(!skip)}
          />
        </Form.Item>
        <Form.Item
          className="!mb-0 w-40 max-w-full"
          label={t("modelProfile.timeout")}
        >
          <InputNumber
            aria-label={t("modelProfile.timeout")}
            className="!w-full"
            value={timeout}
            disabled={pending}
            min={1}
            max={2147483646}
            precision={0}
            onChange={(value) => {
              if (value !== null) onTimeoutChange(value);
            }}
          />
        </Form.Item>
      </div>
      {onHeadersChange && (
        <div>
          <h5 className="text-xs font-medium">
            {t("modelProfile.httpHeaders")}
          </h5>
          <p className="mb-2 text-xs text-muted-foreground">
            {t("modelProfile.httpHeadersHint")}
          </p>
          <HttpHeadersEditor
            value={headers ?? {}}
            onChange={onHeadersChange}
            onValidityChange={onValidityChange}
            disabled={pending}
          />
        </div>
      )}
    </section>
  );
}
