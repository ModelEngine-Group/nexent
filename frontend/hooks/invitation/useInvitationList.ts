import { useQuery } from "@tanstack/react-query";
import { listInvitations } from "@/services/invitationService";
import type { InvitationListRequest } from "@/services/invitationService";

export function useInvitationList(request: InvitationListRequest) {
  return useQuery({
    queryKey: ["invitations", request.tenant_id, request.page, request.page_size, request.sort_by, request.sort_order],
    queryFn: () => listInvitations(request),
    enabled: Boolean(request.tenant_id),
    staleTime: 1000 * 30,
    refetchOnMount: 'always', // Always refetch when component mounts (e.g., when switching tabs)
  });
}
