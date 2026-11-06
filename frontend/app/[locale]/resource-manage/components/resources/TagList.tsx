// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState } from "react";
import { Alert, Empty, Select, Spin } from "antd";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { StandardButton } from "@/components/common/StandardButton";
import TagDefinitionManagementPanel from "@/components/tag/TagDefinitionManagementPanel";
import { USER_ROLES } from "@/const/auth";
import { tagManagementApi } from "@/services/tagManagementService";

interface TagListProps {
  tenantId: string;
}

export default function TagList({ tenantId }: TagListProps) {
  const { t } = useTranslation("common");
  const { user } = useAuthorizationContext();

  // Tag APIs resolve the tenant from authentication, not a request parameter.
  if (!user?.tenantId || user.tenantId !== tenantId) {
    return (
      <Alert
        type="info"
        showIcon
        title={t("tagManagement.currentTenantOnly")}
      />
    );
  }

  const canManage = [
    USER_ROLES.SU,
    USER_ROLES.ADMIN,
    USER_ROLES.SPEED,
    USER_ROLES.ASSET_OWNER,
  ].includes(user.role as USER_ROLES);

  return (
    <TenantTagList key={tenantId} tenantId={tenantId} canManage={canManage} />
  );
}

function TenantTagList({
  tenantId,
  canManage,
}: TagListProps & { canManage: boolean }) {
  const { t } = useTranslation("common");
  const [selectedLibraryId, setSelectedLibraryId] = useState<number | null>(
    null
  );
  const {
    data: libraries,
    isPending,
    error,
    refetch,
  } = useQuery({
    queryKey: ["tagLibraries", tenantId],
    queryFn: () => tagManagementApi.listLibraries(),
  });
  const library =
    libraries?.find((item) => item.bucket_id === selectedLibraryId) ??
    libraries?.find((item) => item.bucket_key === "default_resource") ??
    libraries?.[0];

  if (isPending) {
    return (
      <div className="flex min-h-40 items-center justify-center">
        <Spin />
      </div>
    );
  }
  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        title={error.message}
        action={
          <StandardButton onClick={() => void refetch()}>
            {t("common.retry")}
          </StandardButton>
        }
      />
    );
  }
  if (!library)
    return <Empty description={t("tagManagement.empty.noLibraries")} />;

  return (
    <div className="h-full min-h-0 overflow-auto pb-4">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span>{t("tagManagement.library")}</span>
        <Select
          aria-label={t("tagManagement.library")}
          className="min-w-48"
          value={library.bucket_id}
          options={libraries?.map((item) => ({
            value: item.bucket_id,
            label: t(`tagManagement.libraries.${item.bucket_key}`, {
              defaultValue: item.bucket_name,
            }),
          }))}
          onChange={setSelectedLibraryId}
        />
      </div>
      <TagDefinitionManagementPanel
        key={library.bucket_id}
        bucketId={library.bucket_id}
        canManage={canManage}
      />
    </div>
  );
}
