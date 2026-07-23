"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Legacy AIDP knowledge base entry page.
 *
 * After the frontend-toggle-plan redesign, the unified entry for all
 * knowledge bases is `/knowledges`, which conditionally renders either
 * `<AidpKnowledgeConfiguration />` or the built-in `<DataConfig />`
 * based on the ENABLE_AIDP_KNOWLEDGE environment variable.
 *
 * This route is retained only for backward compatibility with existing
 * bookmarks and links. It immediately redirects to `/knowledges` once
 * the deployment config is ready.
 */
export default function AidpKnowledgePage() {
  const router = useRouter();

  // Redirect to the unified `/knowledges` entry as soon as the page mounts.
  // We don't gate this on deployment config because the unified entry
  // handles both branches itself.
  useEffect(() => {
    router.replace("/knowledges");
  }, [router]);

  return null;
}
