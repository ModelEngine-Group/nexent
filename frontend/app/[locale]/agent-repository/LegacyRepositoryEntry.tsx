// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { buildLegacyRepositoryRedirect } from "@/lib/legacyRepositoryRoutes";

export default function LegacyRepositoryEntry() {
  const { locale } = useParams<{ locale: string }>();
  const router = useRouter();
  const params = useSearchParams();
  const href = buildLegacyRepositoryRedirect(locale || "en", params.toString());
  useEffect(() => {
    if (href) router.replace(href);
  }, [href, router]);
  return null;
}
