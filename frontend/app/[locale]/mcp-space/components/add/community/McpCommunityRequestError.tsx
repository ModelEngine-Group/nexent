// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Button } from "antd";
import { useTranslation } from "react-i18next";

export default function McpCommunityRequestError({
  onRetry,
}: {
  onRetry: () => void;
}) {
  const { t } = useTranslation("common");
  return (
    <div role="alert" className="space-y-3 text-center">
      <p>{t("mcpTools.community.requestFailed")}</p>
      <Button type="primary" onClick={onRetry}>
        {t("repository.common.retry")}
      </Button>
    </div>
  );
}
