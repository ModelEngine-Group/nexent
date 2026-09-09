"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { withBasePath } from "@/lib/basePath";

export default function WorkbenchRedirect() {
  const router = useRouter();
  const { locale } = useParams<{ locale: string }>();
  useEffect(() => {
    router.replace(
      withBasePath(
        `/${locale}/newchat${window.location.search}${window.location.hash}`
      )
    );
  }, [locale, router]);
  return null;
}
