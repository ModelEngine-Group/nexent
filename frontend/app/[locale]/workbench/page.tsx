"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useDeployment } from "@/components/providers/deploymentProvider";
import WorkbenchPage from "@/features/workbench/WorkbenchPage";

export default function WorkbenchRoute() {
  const router = useRouter();
  const { isDeploymentReady, enableAgentWorkbench } = useDeployment();

  useEffect(() => {
    if (isDeploymentReady && !enableAgentWorkbench) router.replace("/");
  }, [isDeploymentReady, enableAgentWorkbench, router]);

  if (!isDeploymentReady || !enableAgentWorkbench) return null;
  return <WorkbenchPage />;
}
