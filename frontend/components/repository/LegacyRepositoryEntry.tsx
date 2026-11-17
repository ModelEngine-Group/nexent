// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect } from "react";
import dynamic from "next/dynamic";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { buildLegacyRepositoryRedirect } from "@/lib/legacyRepositoryRoutes";
import type { ResourceType } from "@/types/resourceRepository";

const MyAgent = dynamic(() =>
  import("./agent/my-agent").then((mod) => mod.MyAgent)
);

export default function LegacyRepositoryEntry({
  resourceType,
}: {
  resourceType: ResourceType;
}) {
  const { locale } = useParams<{ locale: string }>();
  const router = useRouter();
  const params = useSearchParams();
  const href = buildLegacyRepositoryRedirect(
    locale || "en",
    resourceType,
    params.toString()
  );
  useEffect(() => {
    if (href) router.replace(href);
  }, [href, router]);
  return href ? null : (
    <div className="h-full min-h-0 overflow-auto p-6">
      <MyAgent active />
    </div>
  );
}
