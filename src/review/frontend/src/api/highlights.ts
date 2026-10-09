/** Backend v1 contracts for manual review and compiled highlight plans. */
import { api } from './client';

export type EventKind =
  | 'impact' | 'sweep' | 'wash' | 'fill' | 'energy_surge' | 'energy_drop'
  | 'silence' | 'vocal_entry' | 'vocal_exit' | 'instrument_entry'
  | 'texture_shift' | 'unknown_texture' | 'chorus_arrival';

export interface EventTiming {
  start_ms: number;
  end_ms: number;
  peak_ms: number | null;
}

export interface MusicalEvent {
  event_id: string;
  source_sha256: string;
  source_revision: string;
  kind: EventKind;
  timing: EventTiming;
  provenance: 'manual' | 'detector' | 'audio_model';
  detection_score: number | null;
  intensity: number | null;
  salience: number | null;
  evidence: { source: string; revision: string; stem: string | null; note: string }[];
}

export interface EventReview {
  event: MusicalEvent;
  status: 'candidate' | 'accepted' | 'dismissed';
  timing_override: EventTiming | null;
  importance: 0 | 1 | 2 | 3 | null;
  locked: boolean;
  note: string;
}

export interface HighlightTreatment {
  treatment_id: string;
  event_id: string;
  recipe_id: 'sustained_wash' | 'isolated_impact';
  targets: string[];
  intensity: number;
  start_anchor: 'start' | 'peak' | 'end';
  end_anchor: 'start' | 'peak' | 'end';
  start_offset_ms: number;
  end_offset_ms: number;
  palette_source: 'section';
  locked: boolean;
  rationale: string;
}

// The backend supplies defaults for optional draft treatment settings.
export type TreatmentInput = Pick<HighlightTreatment, 'treatment_id' | 'event_id' | 'recipe_id' | 'targets'>
  & Partial<Omit<HighlightTreatment, 'treatment_id' | 'event_id' | 'recipe_id' | 'targets'>>;

export interface HighlightPlan {
  schema_version: 1;
  plan_id: string;
  revision: number;
  context: {
    source_sha256: string;
    duration_ms: number;
    analysis_revision: string;
    sections_sha256: string;
    layout_sha256: string;
    themes_sha256: string;
    catalog_sha256: string;
    baseline_sha256: string;
    variation_seed: number;
    recipe_version: string;
  };
  events: EventReview[];
  treatments: HighlightTreatment[];
  provenance: {
    origin: 'manual' | 'local' | 'ai';
    provider: string | null;
    model: string | null;
    prompt_version: string | null;
  };
}

export interface HighlightState {
  schema_version: 1;
  source_sha256: string;
  duration_ms: number;
  revision: number;
  events: EventReview[];
  draft_plan: HighlightPlan | null;
  accepted_plan: HighlightPlan | null;
  previous_accepted_plan: HighlightPlan | null;
  enabled: boolean;
}

export interface HighlightResponse {
  state: HighlightState;
  // Reject/disable work even without audio, and return a null source.
  source: { source_sha256: string; duration_ms: number } | null;
  issues: { code: string; message?: string; plan?: 'draft_plan' | 'accepted_plan'; event_ids?: string[] }[];
  plan_validation: {
    status: 'valid' | 'not_checked' | 'no_plan';
    plan_id: string | null;
    reason: string;
  };
}

export interface EventEdit {
  expected_revision: number;
  source_sha256: string;
  duration_ms: number;
  events: EventReview[];
}

export interface PreviewOptions {
  section_index?: number | null;
  highlights?: boolean;
  variation_seed?: number;
  vocal_diarization?: boolean;
  include_extra_timing?: boolean;
}

export interface HighlightPreview {
  preview_id: string;
  cached: boolean;
  status: 'done';
  variation_seed: number;
  highlights: boolean;
  highlight_revision: number | null;
  result: {
    section: { index: number; label: string; role: string; start_ms: number; end_ms: number; energy_score: number };
    window_ms: number;
    theme_name: string;
    placement_count: number;
    // Backend-relative download URL; UI links should resolve it with apiUrl().
    artifact_url: string;
    warnings: string[];
  };
}

const path = (songId: string) => `/songs/${encodeURIComponent(songId)}/highlights`;

export const highlightsApi = {
  get: (songId: string, signal?: AbortSignal) =>
    api.get<HighlightResponse>(path(songId), signal),
  saveEvents: (songId: string, edit: EventEdit) =>
    api.put<HighlightResponse>(path(songId), edit),
  prepareDraft: (songId: string, draft: {
    expected_revision: number; treatments: TreatmentInput[]; variation_seed?: number;
  }) => api.post<HighlightResponse>(`${path(songId)}/draft`, draft),
  acceptDraft: (songId: string, revision: number, planId: string) =>
    api.post<HighlightResponse>(`${path(songId)}/accept`, { expected_revision: revision, plan_id: planId }),
  rejectDraft: (songId: string, revision: number, planId: string) =>
    api.post<HighlightResponse>(`${path(songId)}/reject`, { expected_revision: revision, plan_id: planId }),
  setEnabled: (songId: string, revision: number, enabled: boolean) =>
    api.post<HighlightResponse>(`${path(songId)}/${enabled ? 'enable' : 'disable'}`, { expected_revision: revision }),
  undo: (songId: string, revision: number) =>
    api.post<HighlightResponse>(`${path(songId)}/undo`, { expected_revision: revision }),
  preview: (songId: string, options: PreviewOptions = {}) =>
    api.post<HighlightPreview>(`/songs/${encodeURIComponent(songId)}/preview`, options),
};
