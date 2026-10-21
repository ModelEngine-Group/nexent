// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Collapse, Form, InputNumber, Switch, type CollapseProps } from "antd";
import { Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { RequestParametersEditor } from "./RequestParametersEditor";

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
}) {
  const { t } = useTranslation();
  return (
    <Collapse
      {...collapse}
      ghost
      expandIconPlacement="end"
      className="border-t [&_.ant-collapse-header]:!bg-transparent [&_.ant-collapse-header]:!px-0 [&_.ant-collapse-header]:!shadow-none [&_.ant-collapse-body]:!px-0"
      items={[
        {
          key: "advanced",
          label: (
            <span className="flex items-center gap-2 text-xs">
              <Settings2 size={14} />
              {t("modelProfile.advanced")}
              <span className="text-muted-foreground">
                {t("modelProfile.layout.advancedHint")}
              </span>
            </span>
          ),
          children: (
            <section
              aria-label={t("modelProfile.requestGroup")}
              className="space-y-3 pt-1"
            >
              <h5 className="mb-2 text-xs font-medium text-muted-foreground">
                {t("modelProfile.httpGroup")}
              </h5>
              <div className="grid grid-cols-2 gap-x-3">
                <Form.Item label={t("modelProfile.skipTlsVerify")}>
                  <Switch
                    aria-label={t("modelProfile.skipTlsVerify")}
                    checked={!sslVerify}
                    onChange={(skip) => onSslVerifyChange(!skip)}
                  />
                </Form.Item>
                <Form.Item label={t("modelProfile.timeout")}>
                  <InputNumber
                    className="!w-full"
                    value={timeout}
                    min={1}
                    max={2147483646}
                    precision={0}
                    onChange={(value) => {
                      if (value !== null) onTimeoutChange(value);
                    }}
                  />
                </Form.Item>
              </div>
              <h5 className="mb-2 mt-3 text-xs font-medium text-muted-foreground">
                {t("modelProfile.extraParameters")}
              </h5>
              <Form.Item>
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
