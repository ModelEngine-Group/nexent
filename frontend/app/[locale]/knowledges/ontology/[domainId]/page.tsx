// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useEffect } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { useDeployment } from "@/components/providers/deploymentProvider";
import AidpOntologyDetailPage from "@/ext_components/aidp/pages/ontology/AidpOntologyDetailPage";

export default function AidpOntologyDetailRoute() {
  const { enableAidpKnowledge, isDeploymentReady } = useDeployment();
  const router = useRouter();
  const params = useParams();
  const locale = (params?.locale as string) || "zh";
  const domainId = decodeURIComponent((params?.domainId as string) || "");
  const searchParams = useSearchParams();
  const createParam = searchParams.get("create");
  const createAction =
    createParam === "entity" || createParam === "metadata"
      ? createParam
      : undefined;

  useEffect(() => {
    if (isDeploymentReady && !enableAidpKnowledge) {
      router.replace(`/${locale}/knowledges`);
    }
  }, [enableAidpKnowledge, isDeploymentReady, locale, router]);

  if (!isDeploymentReady) {
    return (
      <div className="flex h-full w-full items-center justify-center text-sm text-gray-400">
        Loading...
      </div>
    );
  }
  if (!enableAidpKnowledge) return null;
  if (!domainId) {
    router.replace(`/${locale}/knowledges/ontology`);
    return null;
  }

  return (
    <div style={{ width: "100%", height: "100%", padding: "0 24px" }}>
      <div className="mt-4 flex h-full min-h-0 w-full flex-col">
        <AidpOntologyDetailPage
          key={`${domainId}-${createAction ?? ""}`}
          domainId={domainId}
          createAction={createAction}
        />
      </div>
    </div>
  );
}
