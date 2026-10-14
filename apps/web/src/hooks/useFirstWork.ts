import { useQuery } from '@tanstack/react-query';
import { firstWorkApi, firstWorkQueryKey, type FirstWorkState } from '../lib/firstWorkApi';

export function useFirstWork(userId: string | null) {
  return useQuery({
    queryKey: firstWorkQueryKey(userId),
    queryFn: firstWorkApi.get,
    enabled: Boolean(userId),
    retry: false,
    staleTime: 0,
    refetchOnMount: 'always',
  });
}

export function needsStaticFirstWorkGuidance(state: FirstWorkState | undefined, projectId: string | null) {
  // The original manuscript may have been deleted while the project still needs static guidance.
  return Boolean(projectId && state?.project_id === projectId && state.static_guidance);
}
