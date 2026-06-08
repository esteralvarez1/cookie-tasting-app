export type ExportFormat = 'csv' | 'json' | 'xlsx';

export type BlockState = {
  tastingSessionConfigId: string;
  sessionId: string;
  participantCode: string;
  format: ExportFormat;
  loading: boolean;
  error: string;
  success: string;
};

export type BlockConfig = {
  id: string;
  title: string;
  description: string;
  endpoint: string;
  formats: ExportFormat[];
  defaultFormat: ExportFormat;
};

export type HealthStatus = 'idle' | 'loading' | 'ok' | 'error';

export type TastingSessionCreate = {
  title?: string;
  sample_codes: string[];
  final_redirect_url?: string;
};

export type TastingSessionConfig = {
  tasting_session_id: string;
  public_token: string;
  title?: string;
  status: 'ACTIVE' | 'CLOSED';
  sample_codes: string[];
  total_samples: number;
  final_redirect_url?: string | null;
};

/** Alias: la respuesta de creación tiene la misma forma. */
export type CreatedTastingSession = TastingSessionConfig;
