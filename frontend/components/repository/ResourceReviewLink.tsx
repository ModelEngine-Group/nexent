// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { buildResourceRepositoryHref } from "@/lib/resourceRepositoryRoutes";

export default function ResourceReviewLink({
  review,
}: {
  review?: {
    review_id: string;
    status: "pending_review" | "approved" | "rejected";
  } | null;
}) {
  const { locale } = useParams<{ locale: string }>();
  const { t } = useTranslation("common");
  if (!review) return null;
  return (
    <Link
      href={buildResourceRepositoryHref(locale || "en", {
        tab: "review",
        reviewId: review.review_id,
      })}
      onClick={(event) => event.stopPropagation()}
      className="pointer-events-auto relative z-10 inline-flex shrink-0 rounded px-1.5 py-0.5 text-xs text-blue-600 hover:underline"
    >
      {t(`resourceCenter.status.${review.status}`)}
    </Link>
  );
}
