// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useId } from "react";
import { Button, Form, Input } from "antd";
import { Plus, X } from "lucide-react";
import { useTranslation } from "react-i18next";

export default function McpHeaderFields({ readOnly }: { readOnly: boolean }) {
  const { t } = useTranslation("common");
  const labelId = useId();

  return (
    <Form.List
      name="customHeaders"
      rules={[
        {
          validator: async (_, rows: { name?: string }[] = []) => {
            const names = rows
              .map((row) => row?.name?.trim().toLowerCase())
              .filter(Boolean);
            if (new Set(names).size !== names.length) {
              throw new Error(t("mcpTools.editDetail.duplicateHeader"));
            }
          },
        },
      ]}
    >
      {(fields, { add, remove }, { errors }) => (
        <Form.Item
          label={
            <span id={labelId}>{t("mcpTools.addModal.customHeaders")}</span>
          }
        >
          <div
            role="group"
            aria-labelledby={labelId}
            className="min-w-0 space-y-2"
          >
            {fields.map(({ key, name }) => (
              <div
                key={key}
                className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] gap-2"
              >
                <Form.Item
                  name={[name, "name"]}
                  className="!mb-0"
                  rules={[
                    {
                      required: true,
                      whitespace: true,
                      message: t("mcpTools.editDetail.headerNameRequired"),
                    },
                    {
                      pattern: /^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/,
                      message: t("mcpTools.editDetail.invalidHeaderName"),
                    },
                  ]}
                >
                  <Input
                    disabled={readOnly}
                    aria-label={t("mcpTools.editDetail.headerName")}
                    placeholder={t("mcpTools.editDetail.headerName")}
                  />
                </Form.Item>
                <Form.Item name={[name, "value"]} className="!mb-0">
                  <Input.Password
                    disabled={readOnly}
                    autoComplete="new-password"
                    aria-label={t("mcpTools.editDetail.headerValue")}
                    placeholder={t("mcpTools.editDetail.headerValue")}
                  />
                </Form.Item>
                {!readOnly && (
                  <Button
                    type="text"
                    icon={<X size={14} />}
                    aria-label={t("mcpTools.editDetail.removeHeader")}
                    onClick={() => remove(name)}
                  />
                )}
              </div>
            ))}
            <Form.ErrorList errors={errors} />
            {!readOnly && (
              <Button
                block
                type="dashed"
                icon={<Plus size={14} />}
                onClick={() => add({ name: "", value: "" })}
              >
                {t("mcpTools.editDetail.addHeader")}
              </Button>
            )}
            {readOnly && fields.length === 0 && (
              <span className="text-muted-foreground">—</span>
            )}
          </div>
        </Form.Item>
      )}
    </Form.List>
  );
}
