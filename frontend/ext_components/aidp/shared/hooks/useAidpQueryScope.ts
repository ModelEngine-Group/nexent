import { useMemo } from "react";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";

/** Scope permission-sensitive caches to the current tenant and account. */
export const useAidpQueryScope = () => {
  const { user } = useAuthorizationContext();
  const { enableAidpKnowledge, isDeploymentReady } = useDeployment();
  const tenantId = user?.tenantId ?? null;
  const userId = user?.id ?? null;
  const key = useMemo(
    () => ["aidpKnowledge", tenantId, userId] as const,
    [tenantId, userId]
  );
  return { key, enabled: !!user && isDeploymentReady && enableAidpKnowledge };
};
