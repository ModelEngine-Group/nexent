"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { conversationService } from "@/services/conversationService";
import { withBasePath } from "@/lib/basePath";
import log from "@/lib/logger";

/** Keep ordinary Agent and Workbench history links on their owning page. */
export function useConversationRouteGuard(
  expected: "agent_chat" | "workbench"
) {
  const router = useRouter();
  const { locale } = useParams<{ locale: string }>();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const rawId = params.get("conversation_id") ?? params.get("thread_id");
    const conversationId = Number(rawId);
    if (!rawId || !Number.isInteger(conversationId) || conversationId <= 0)
      return;

    let cancelled = false;
    void conversationService
      .getById(String(conversationId))
      .then((conversation) => {
        if (cancelled) return;
        const actual = conversation.workbench_config
          ? "workbench"
          : "agent_chat";
        if (actual === expected) return;
        const route = actual === "workbench" ? "workbench" : "newchat";
        router.replace(
          withBasePath(
            `/${locale}/${route}${window.location.search}${window.location.hash}`
          )
        );
      })
      .catch((error) =>
        log.warn("Failed to resolve conversation entrypoint", error)
      );
    return () => {
      cancelled = true;
    };
  }, [expected, locale, router]);
}
