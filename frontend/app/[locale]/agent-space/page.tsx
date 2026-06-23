"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Legacy Agent Space route — redirects to Agent Repository.
 */
export default function AgentSpaceRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/agent-repository");
  }, [router]);

  return null;
}
