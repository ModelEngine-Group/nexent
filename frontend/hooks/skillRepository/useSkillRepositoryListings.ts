import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import skillRepositoryService from "@/services/skillRepositoryService";
import type {
  MyEditableSkillListParams,
  SkillRepositoryListingCreatePayload,
  SkillRepositoryListingListParams,
  SkillRepositoryListingStatus,
} from "@/types/skillRepository";

export const SKILL_REPOSITORY_LISTINGS_QUERY_KEY = "skillRepositoryListings";
export const SKILL_REPOSITORY_DETAIL_QUERY_KEY = "skillRepositoryListingDetail";
export const MY_EDITABLE_SKILLS_QUERY_KEY = "myEditableSkills";
export const SKILLS_LIST_QUERY_KEY = "skills";

export async function invalidateSkillRepositoryCaches(
  queryClient: QueryClient
) {
  const keys = [
    [SKILL_REPOSITORY_LISTINGS_QUERY_KEY],
    [MY_EDITABLE_SKILLS_QUERY_KEY],
    [SKILL_REPOSITORY_DETAIL_QUERY_KEY],
  ] as const;

  await Promise.all(
    keys.map((queryKey) =>
      queryClient.refetchQueries({ queryKey, type: "all" })
    )
  );
}

export function useSkillRepositoryListings(
  params?: SkillRepositoryListingListParams,
  enabled = true
) {
  return useQuery({
    queryKey: [SKILL_REPOSITORY_LISTINGS_QUERY_KEY, params],
    queryFn: () => skillRepositoryService.fetchSkillRepositoryListings(params),
    staleTime: 60_000,
    refetchOnMount: "always",
    enabled,
  });
}

export function useMyEditableSkills(
  params?: MyEditableSkillListParams,
  enabled = true
) {
  return useQuery({
    queryKey: [MY_EDITABLE_SKILLS_QUERY_KEY, params],
    queryFn: () => skillRepositoryService.fetchMyEditableSkills(params),
    staleTime: 60_000,
    refetchOnMount: "always",
    enabled,
  });
}

export function useSkillRepositoryListingDetail(
  skillRepositoryId: number | null,
  enabled = true
) {
  return useQuery({
    queryKey: [SKILL_REPOSITORY_DETAIL_QUERY_KEY, skillRepositoryId],
    queryFn: () =>
      skillRepositoryService.fetchSkillRepositoryListingDetail(
        skillRepositoryId as number
      ),
    staleTime: 60_000,
    enabled: enabled && skillRepositoryId != null,
  });
}

export function useUpdateSkillRepositoryStatus() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      skillRepositoryId,
      status,
    }: {
      skillRepositoryId: number;
      status: SkillRepositoryListingStatus;
    }) =>
      skillRepositoryService.updateSkillRepositoryStatus(
        skillRepositoryId,
        status
      ),
    onSuccess: async () => {
      await invalidateSkillRepositoryCaches(queryClient);
    },
  });
}

export function useCreateSkillRepositoryListing() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      skillId,
      payload,
    }: {
      skillId: number;
      payload: SkillRepositoryListingCreatePayload;
    }) =>
      skillRepositoryService.createSkillRepositoryListing(skillId, payload),
    onSuccess: async () => {
      await invalidateSkillRepositoryCaches(queryClient);
    },
  });
}

export function useInstallSkillFromRepository() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (skillRepositoryId: number) =>
      skillRepositoryService.installSkillFromRepository(skillRepositoryId),
    onSuccess: async () => {
      await Promise.all([
        invalidateSkillRepositoryCaches(queryClient),
        queryClient.invalidateQueries({ queryKey: [SKILLS_LIST_QUERY_KEY] }),
      ]);
    },
  });
}
