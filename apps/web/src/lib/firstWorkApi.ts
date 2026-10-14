import { api } from './apiClient';
import type { ProjectType } from '../types';

export interface FirstWorkState {
  status: 'ineligible' | 'pending' | 'disabled' | 'waiting_verification' | 'waiting_onboarding' | 'skipped_existing' | 'created';
  project_id: string | null;
  file_id: string | null;
  available: boolean;
  static_guidance: boolean;
  opened_at: string | null;
  first_manual_write_at: string | null;
  first_ai_requested_at: string | null;
}

export const firstWorkQueryKey = (userId: string | null) => ['workspace-first-work', userId] as const;
export const firstWorkApi = {
  get: () => api.get<FirstWorkState>('/api/v1/workspace/first-work'),
  initialize: (preferredType: ProjectType, language: string) =>
    api.post<FirstWorkState>('/api/v1/workspace/first-work', { preferred_type: preferredType }, {
      headers: { 'Accept-Language': language },
    }),
  open: () => api.post<FirstWorkState>('/api/v1/workspace/first-work/open'),
};
