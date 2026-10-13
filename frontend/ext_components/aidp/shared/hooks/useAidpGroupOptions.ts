import { useMemo } from "react";

import { USER_ROLES } from "@/const/auth";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useGroupList } from "@/hooks/group/useGroupList";
import { usePermission } from "@/hooks/permission/usePermission";

export interface AidpGroupOption {
  value: number;
  label: string;
}

export const useAidpGroupOptions = () => {
  const { user } = useAuthorizationContext();
  const { can, isReady } = usePermission();
  const canReadGroups = can("group:read");
  const isUser = user?.role === USER_ROLES.USER;
  const canConfigureGroupPermissions = Boolean(user) && !isUser;
  const tenantId = user?.tenantId ?? null;
  const groupQuery = useGroupList(canReadGroups ? tenantId : null);
  const groupListData = groupQuery.data;
  const groupOptions = useMemo<AidpGroupOption[]>(
    () =>
      (groupListData?.groups ?? []).map((group) => ({
        value: group.group_id,
        label: group.group_name,
      })),
    [groupListData]
  );

  return {
    isUser,
    canConfigureGroupPermissions,
    canReadGroups,
    groupOptions,
    groupsLoading: !isReady || groupQuery.isFetching,
    groupsError: groupQuery.error,
  };
};
