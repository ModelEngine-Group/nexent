// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { App, Modal } from "antd";

import type { AidpKnowledgeBaseItem } from "@/ext_components/aidp/shared/types/knowledge";
import type { AidpDocumentItem } from "@/ext_components/aidp/shared/types/management";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import { useErrorHandler } from "@/hooks/useErrorHandler";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useAidpKnowledgeCache } from "@/ext_components/aidp/shared/hooks/useAidpKnowledgeCache";
import { useDeleteAidpKnowledgeBase } from "@/ext_components/aidp/pages/knowledge-list/hooks/useAidpKnowledgeList";

import AidpKnowledgeFilesPage from "./AidpKnowledgeFilesPage";

/**
 * Dedicated AIDP knowledge base detail page.
 *
 * Renders the detail view for the knowledge base referenced by the `kb` query
 * parameter, so the URL stays stable across browser refreshes and deep links.
 * Visitors go back to the knowledge base overview when the deployment does not
 * have the AIDP backend enabled, the id is missing, or the knowledge base
 * cannot be loaded.
 */
const AidpKnowledgeDetailPage: React.FC = () => {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const router = useRouter();
  const params = useParams();
  const searchParams = useSearchParams();
  const locale = (params?.locale as string) || "zh";
  const { enableAidpKnowledge, isDeploymentReady } = useDeployment();
  const kbId = searchParams?.get("kb") || null;
  const tabParam = searchParams?.get("tab");
  const initialTab =
    tabParam === "tasks" || tabParam === "information" ? tabParam : "files";
  const initialFolder = searchParams?.get("folder") || "/";
  const { updateKnowledgeBase, fetchKnowledgeBase } = useAidpKnowledgeCache();
  const deleteMutation = useDeleteAidpKnowledgeBase();
  const { handleError } = useErrorHandler();

  const [kb, setKb] = useState<AidpKnowledgeBaseItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  // The entry only serves AIDP; an ES deployment keeps its own detail flow,
  // so a direct visit goes back to the knowledge base page.
  useEffect(() => {
    if (!isDeploymentReady) return;
    if (!enableAidpKnowledge) {
      router.replace(`/${locale}/knowledges`);
    }
  }, [enableAidpKnowledge, isDeploymentReady, locale, router]);

  useEffect(() => {
    if (!isDeploymentReady || !enableAidpKnowledge) return;
    if (!kbId) {
      router.replace(`/${locale}/knowledges`);
      return;
    }
    let cancelled = false;
    fetchKnowledgeBase(kbId)
      .then((detail) => {
        if (cancelled) return;
        setKb({
          ...detail,
          kds_id: kbId,
          kds_name: detail.kds_name || kbId,
        } as AidpKnowledgeBaseItem);
      })
      .catch((error) => {
        if (cancelled) return;
        handleError(error, {
          showMessage: false,
          handleSession: false,
        });
        message.error(
          getAidpErrorMessage(error, t, t("aidpKnowledge.detailLoadFailed"))
        );
        router.replace(`/${locale}/knowledges`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    enableAidpKnowledge,
    fetchKnowledgeBase,
    handleError,
    isDeploymentReady,
    kbId,
    locale,
    message,
    router,
    t,
  ]);

  const handleBack = useCallback(() => {
    router.push(`/${locale}/knowledges`);
  }, [locale, router]);

  const handleDelete = useCallback(
    (target: AidpKnowledgeBaseItem) => {
      setDeleteConfirmOpen(true);
      Modal.confirm({
        title: t("aidpKnowledge.confirmDeleteTitle"),
        content: t("aidpKnowledge.confirmDeleteContent", {
          name: target.kds_name,
        }),
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        centered: true,
        afterClose: () => setDeleteConfirmOpen(false),
        onOk: async () => {
          try {
            await deleteMutation.mutateAsync(target.kds_id);
            message.success(t("aidpKnowledge.deleteKbSuccess"));
            router.push(`/${locale}/knowledges`);
          } catch (error) {
            handleError(error, {
              showMessage: false,
              handleSession: false,
            });
            message.error(
              getAidpErrorMessage(error, t, t("aidpKnowledge.deleteKbFailed"))
            );
            throw error;
          }
        },
      });
    },
    [deleteMutation, handleError, locale, message, router, t]
  );

  const handleUpdated = useCallback(
    (updated: AidpKnowledgeBaseItem) => {
      setKb((current) => (current ? { ...current, ...updated } : current));
      updateKnowledgeBase(updated);
    },
    [updateKnowledgeBase]
  );

  // File detail is its own route; carry the display fields and the current
  // folder so returning from the detail restores the same listing level.
  const handleOpenFile = useCallback(
    (file: AidpDocumentItem, folderPath: string) => {
      if (!kbId || !file.file_uuid) return;
      const search = new URLSearchParams({ kb: kbId, file: file.file_uuid });
      if (file.file_name) search.set("name", file.file_name);
      if (file.file_type) search.set("type", file.file_type);
      if (typeof file.file_size === "number") {
        search.set("size", String(file.file_size));
      }
      if (folderPath && folderPath !== "/") search.set("folder", folderPath);
      router.push(`/${locale}/knowledges/detail/file?${search.toString()}`);
    },
    [kbId, locale, router]
  );

  // Keep the folder in the URL while browsing the list so browser back from a
  // file detail returns to the same folder instead of the root.
  const handleFolderChange = useCallback(
    (folderPath: string) => {
      if (!kbId) return;
      const search = new URLSearchParams({ kb: kbId, tab: "files" });
      if (folderPath && folderPath !== "/") search.set("folder", folderPath);
      router.replace(`/${locale}/knowledges/detail?${search.toString()}`);
    },
    [kbId, locale, router]
  );

  if (!isDeploymentReady || loading || !kb) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <span className="text-sm text-gray-400">Loading...</span>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full min-w-0 flex-col">
      <div className="mt-4 min-h-0 flex-1 overflow-hidden">
        <AidpKnowledgeFilesPage
          key={`${kb.kds_id}:${initialTab}`}
          knowledgeBase={kb}
          onBack={handleBack}
          onDelete={handleDelete}
          onUpdated={handleUpdated}
          onOpenFile={handleOpenFile}
          onFolderChange={handleFolderChange}
          pollingPaused={deleteConfirmOpen}
          initialTab={initialTab}
          initialFolder={initialFolder}
        />
      </div>
    </div>
  );
};

export default AidpKnowledgeDetailPage;
