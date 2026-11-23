// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Button, Form } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

export default function McpTagField({
  children,
  disabled,
  onEdit,
}: {
  children: ReactNode;
  disabled?: boolean;
  onEdit: () => void;
}) {
  const { t } = useTranslation("common");

  return (
    <Form.Item label={t("mcpTools.form.tagsOptional")}>
      <div className="flex min-h-8 min-w-0 items-center gap-2 rounded border border-border px-3">
        <div className="min-w-0 flex-1 overflow-hidden whitespace-nowrap">
          {children}
        </div>
        <Button type="link" size="small" disabled={disabled} onClick={onEdit}>
          {t("tagManagement.action.editTags")}
        </Button>
      </div>
    </Form.Item>
  );
}
