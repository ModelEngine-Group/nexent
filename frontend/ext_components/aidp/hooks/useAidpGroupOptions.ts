import { useMemo } from "react";

import { USER_ROLES } from "@/const/auth";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useGroupList } from "@/hooks/group/useGroupList";

export interface AidpGroupOption {
  value: number;
  label: string;
}

export const useAidpGroupOptions = () => {
  const { user } = useAuthorizationContext();
  const isUser = user?.role === USER_ROLES.USER;
  const canConfigureGroupPermissions = Boolean(user) && !isUser;
  const tenantId = user?.tenantId ?? null;
  const { data: groupListData } = useGroupList(
    canConfigureGroupPermissions ? tenantId : null
  );
  const groupOptions = useMemo<AidpGroupOption[]>(
    () =>
      (groupListData?.groups ?? []).map((group) => ({
        value: group.group_id,
        label: group.group_name,
      })),
    [groupListData]
  );

  return { isUser, canConfigureGroupPermissions, groupOptions };
};
