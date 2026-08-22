"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Legacy Agent Repository route — redirects to Agent Space.
 */
export default function AgentRepositoryRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/agent-space");
  }, [router]);

  return null;
}
