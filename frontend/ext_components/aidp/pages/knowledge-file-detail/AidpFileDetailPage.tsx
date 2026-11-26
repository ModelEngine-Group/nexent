// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { Alert } from "antd";

import type { AidpDocumentItem } from "@/ext_components/aidp/shared/types/management";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useAidpKnowledgeDetail } from "@/ext_components/aidp/pages/knowledge-files/hooks/useAidpKnowledgeDetail";

import AidpFileDetailView from "./AidpFileDetailView";

/**
 * One ingested file as its own routed page.
 *
 * The URL is the source of truth (kb + file + display fields), so refreshing,
 * deep linking and the browser back button all behave like a normal page.
 * The knowledge base detail stays a separate route; this page never renders
 * the knowledge base header or tab bar.
 */
const AidpFileDetailPage: React.FC = () => {
  const { t } = useTranslation();
  const router = useRouter();
  const params = useParams();
  const searchParams = useSearchParams();
  const locale = (params?.locale as string) || "zh";
  const { enableAidpKnowledge, isDeploymentReady } = useDeployment();

  const kbId = searchParams?.get("kb") || "";
  const fileUuid = searchParams?.get("file") || "";
  const fileName = searchParams?.get("name") || "";
  const fileType = searchParams?.get("type") || "";
  const fileSizeParam = searchParams?.get("size") || "";
  const folderParam = searchParams?.get("folder") || "";

  const detailQuery = useAidpKnowledgeDetail(kbId);
  const detail = detailQuery.data;

  const filesUrl = useMemo(() => {
    const search = new URLSearchParams({ kb: kbId, tab: "files" });
    if (folderParam) search.set("folder", folderParam);
    return `/${locale}/knowledges/detail?${search.toString()}`;
  }, [folderParam, kbId, locale]);

  // A missing deployment/kb/file must not render a half-empty page. The file
  // list route is the closest valid target when only the file id is missing.
  useEffect(() => {
    if (!isDeploymentReady) return;
    if (!enableAidpKnowledge || !kbId) {
      router.replace(`/${locale}/knowledges`);
      return;
    }
    if (!fileUuid) {
      router.replace(filesUrl);
    }
  }, [
    enableAidpKnowledge,
    fileUuid,
    filesUrl,
    isDeploymentReady,
    kbId,
    locale,
    router,
  ]);

  const handleBack = useCallback(() => {
    // Return to the file list at the folder recorded in this URL. Replacing
    // keeps the browser back button from bouncing between the two entries.
    router.replace(filesUrl);
  }, [filesUrl, router]);

  const file = useMemo<AidpDocumentItem>(() => {
    const size = Number(fileSizeParam);
    const derivedType =
      fileType ||
      (fileName.includes(".")
        ? (fileName.split(".").pop() || "").toLowerCase()
        : "");
    return {
      file_uuid: fileUuid,
      file_ino_no: "",
      file_name: fileName || fileUuid,
      ...(derivedType ? { file_type: derivedType } : {}),
      ...(Number.isFinite(size) && fileSizeParam ? { file_size: size } : {}),
    };
  }, [fileSizeParam, fileType, fileUuid, fileName]);

  if (!isDeploymentReady || !kbId || !fileUuid) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <span className="text-sm text-gray-400">Loading...</span>
      </div>
    );
  }

  if (detailQuery.isError) {
    return (
      <div className="flex h-full w-full flex-col gap-4 pt-4">
        <Alert
          type="error"
          showIcon
          title={getAidpErrorMessage(
            detailQuery.error,
            t,
            t("aidpKnowledge.detailLoadFailed")
          )}
        />
        <button
          type="button"
          className="w-fit text-sm text-blue-600 hover:text-blue-700"
          onClick={handleBack}
        >
          {t("common.back")}
        </button>
      </div>
    );
  }

  if (detailQuery.isPending) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <span className="text-sm text-gray-400">Loading...</span>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full min-w-0 flex-col">
      <div className="mt-4 min-h-0 flex-1 overflow-hidden">
        <AidpFileDetailView
          kdsId={kbId}
          file={file}
          canEdit={detail?.permission === "EDIT"}
          summaryEnabled={detail?.summary_enable === true}
          summaryPreview={detail?.summary_preview === true}
          binding={
            detail
              ? {
                  id: detail.bind_lib_id,
                  type: detail.bind_lib_type,
                  name: detail.bind_lib_name,
                }
              : undefined
          }
          onBack={handleBack}
        />
      </div>
    </div>
  );
};

export default AidpFileDetailPage;
