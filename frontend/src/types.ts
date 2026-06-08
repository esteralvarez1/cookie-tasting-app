export type PublicTastingSession = {
  tasting_session_id: string;
  public_token: string;
  title?: string;
  status: 'ACTIVE' | 'CLOSED';
  sample_codes: string[];
  total_samples: number;
  final_redirect_url?: string | null;
};

export type ParticipantSession = {
  session_id: string;
  participant_code: string;
  tasting_session_id: string;
  session_token: string;
  session_token_expires_at?: string;
  completed_sample_codes: string[];
  pending_sample_codes: string[];
  status: 'CREATED' | 'IN_PROGRESS' | 'COMPLETED';
};

export type EvaluationData = {
  evaluation_id: string;
  session_id: string;
  sample_code: string;
  presentation_order: number;
  status: string;
  current_state: string;
  current_modality: string | null;
  next_question?: string;
  bot_message?: string;
};

export type Turn = {
  turn_index: number;
  speaker: string;
  message_type: string;
  message_text: string;
  created_at: string;
};

export type ModalityAnalysisPayload = {
  mention_text: string;
  descriptor_text: string;
  valuation_text: string;
  is_complete: boolean;
};

export type DialogueAnalysisPayload = {
  analysis_scope: string;
  is_vague: boolean;
  has_comparison: boolean;
  reasoning_summary: string;
  next_action: string | null;
  modalities: Record<string, ModalityAnalysisPayload>;
};

export type DialogueResponseData = EvaluationData & {
  analysis: DialogueAnalysisPayload | null;
  next_step: string | null;
  turns: Turn[];
};

export type SessionNextStep = {
  session_id: string;
  next_step: 'NEXT_SAMPLE' | 'SESSION_COMPLETED' | 'SAMPLE_COMMENT';
  next_sample_index: number;
  completed_sample_codes: string[];
  pending_sample_codes: string[];
  pending_comment_evaluation_id?: string;
  pending_comment_sample_code?: string;
};
