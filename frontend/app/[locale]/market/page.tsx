"use client";

import { useEffect } from "react";
import { useRouter, useParams } from "next/navigation";

/**
 * Legacy /market route — redirects to /market-v2.
 *
 * The old "Agent Market" page (browse remote agent templates, download via
 * import wizard) has been superseded by the unified market-v2 page which
 * shows built-in solutions + agents + skills + MCPs and lets users start
 * chatting directly.
 */
export default function MarketRedirect() {
  const router = useRouter();
  const params = useParams();
  const locale = (params?.locale as string) || "zh";

  useEffect(() => {
    router.replace(`/${locale}/market-v2`);
  }, [router, locale]);

  return (
    <div className="flex items-center justify-center h-screen w-full">
      <div className="text-slate-400 text-sm">Loading…</div>
    </div>
  );
}
