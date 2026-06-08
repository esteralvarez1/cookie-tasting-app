const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
const ADMIN_API_KEY = import.meta.env.VITE_ADMIN_API_KEY;

export type ApiErrorKind =
  | 'NETWORK_ERROR'
  | 'SESSION_EXPIRED'
  | 'TASTING_SESSION_CLOSED'
  | 'INVALID_PUBLIC_LINK'
  | 'INVALID_SAMPLE_CODE'
  | 'LLM_ANALYSIS_ERROR'
  | 'RATE_LIMITED'
  | 'VALIDATION_ERROR'
  | 'SERVER_ERROR'
  | 'UNKNOWN_ERROR';

export class ApiError extends Error {
  status: number;
  detail: string;
  kind: ApiErrorKind;
  path: string;

  constructor(params: {
    status: number;
    detail: string;
    kind: ApiErrorKind;
    userMessage: string;
    path: string;
  }) {
    super(params.userMessage);
    this.name = 'ApiError';
    this.status = params.status;
    this.detail = params.detail;
    this.kind = params.kind;
    this.path = params.path;
  }
}

function buildHeaders(optionsHeaders: HeadersInit | undefined, sessionToken?: string) {
  return {
    'Content-Type': 'application/json',
    ...(sessionToken ? { 'X-Session-Token': sessionToken } : {}),
    ...(optionsHeaders || {}),
  };
}

function extractErrorDetail(payload: unknown): string {
  if (typeof payload === 'string') {
    return payload.trim() || 'Error inesperado';
  }

  if (!payload || typeof payload !== 'object') {
    return 'Error inesperado';
  }

  const data = payload as Record<string, unknown>;
  const detail = data.detail;

  if (typeof detail === 'string') {
    return detail;
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (!item || typeof item !== 'object') return String(item);
        const validationItem = item as Record<string, unknown>;
        return typeof validationItem.msg === 'string' ? validationItem.msg : JSON.stringify(validationItem);
      })
      .join(' ');
  }

  const error = data.error;
  if (error && typeof error === 'object') {
    const errorData = error as Record<string, unknown>;
    if (typeof errorData.message === 'string') return errorData.message;
  }

  return 'Error inesperado';
}

function classifyApiError(status: number, detail: string, path: string): { kind: ApiErrorKind; userMessage: string } {
  const normalizedDetail = detail.toLowerCase();

  if (detail === 'session_expired' || normalizedDetail.includes('valid participant session token required')) {
    return {
      kind: 'SESSION_EXPIRED',
      userMessage: 'Tu sesión ha caducado. Vuelve a introducir tu código.',
    };
  }

  if (
    normalizedDetail.includes('tasting session is not active') ||
    normalizedDetail.includes('sesión de cata está cerrada') ||
    normalizedDetail.includes('sesion de cata esta cerrada')
  ) {
    return {
      kind: 'TASTING_SESSION_CLOSED',
      userMessage: 'Esta cata ya no está activa.',
    };
  }

  if (normalizedDetail.includes('código de muestra no pertenece') || normalizedDetail.includes('codigo de muestra no pertenece')) {
    return {
      kind: 'INVALID_SAMPLE_CODE',
      userMessage: 'Ese código de muestra no pertenece a esta cata.',
    };
  }

  if (status === 404 && normalizedDetail.includes('tasting session not found')) {
    return {
      kind: 'INVALID_PUBLIC_LINK',
      userMessage: 'El enlace de la cata no es válido. Contacta con el administrador.',
    };
  }

  if (status === 429) {
    return {
      kind: 'RATE_LIMITED',
      userMessage: 'Se han enviado demasiadas peticiones. Espera unos segundos e inténtalo de nuevo.',
    };
  }

  if (status === 422 || status === 400) {
    return {
      kind: 'VALIDATION_ERROR',
      userMessage: 'Hay algún dato incorrecto. Revisa la información e inténtalo de nuevo.',
    };
  }

  if (status >= 500 && path.includes('/dialog')) {
    return {
      kind: 'LLM_ANALYSIS_ERROR',
      userMessage: 'Ha habido un problema analizando tu respuesta. Inténtalo de nuevo.',
    };
  }

  if (status >= 500) {
    return {
      kind: 'SERVER_ERROR',
      userMessage: 'Ha ocurrido un problema en el servidor. Inténtalo de nuevo.',
    };
  }

  return {
    kind: 'UNKNOWN_ERROR',
    userMessage: detail || 'Ha ocurrido un error inesperado.',
  };
}

async function request(path: string, options: RequestInit = {}, sessionToken?: string): Promise<any> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: buildHeaders(options.headers, sessionToken),
    });
  } catch {
    throw new ApiError({
      status: 0,
      detail: 'NETWORK_ERROR',
      kind: 'NETWORK_ERROR',
      userMessage: 'No se puede conectar con el servidor.',
      path,
    });
  }

  const isJson = response.headers.get('content-type')?.includes('application/json');
  let payload: any;
  try {
    payload = isJson ? await response.json() : await response.text();
  } catch {
    payload = '';
  }

  if (!response.ok) {
    const detail = extractErrorDetail(payload);
    const classification = classifyApiError(response.status, detail, path);
    throw new ApiError({
      status: response.status,
      detail,
      path,
      ...classification,
    });
  }

  return payload;
}

export const api = {
  getPublicTastingSession: (token: string) =>
    request(`/api/v1/tasting-sessions/public/${encodeURIComponent(token)}`),
  createSession: (participantCode: string, tastingSessionId: string) =>
    request('/api/v1/sessions', { method: 'POST', body: JSON.stringify({ participant_code: participantCode, tasting_session_id: tastingSessionId }) }),
  createEvaluation: (sessionId: string, sampleCode: string, sessionToken: string) =>
    request('/api/v1/evaluations', { method: 'POST', body: JSON.stringify({ session_id: sessionId, sample_code: sampleCode }) }, sessionToken),
  sendDialog: (evaluationId: string, userMessage: string, sessionToken: string) =>
    request(`/api/v1/evaluations/${evaluationId}/dialog`, { method: 'POST', body: JSON.stringify({ user_message: userMessage }) }, sessionToken),
  saveSampleComment: (evaluationId: string, comment: string, sessionToken: string) =>
    request(`/api/v1/evaluations/${evaluationId}/final-comment`, { method: 'POST', body: JSON.stringify({ comment }) }, sessionToken),
  getSessionNextStep: (sessionId: string, sessionToken: string) =>
    request(`/api/v1/sessions/${sessionId}/next-step`, {}, sessionToken),
  getEvaluation: (evaluationId: string, sessionToken: string) =>
    request(`/api/v1/evaluations/${evaluationId}`, {}, sessionToken),
  getEvaluationConversation: (evaluationId: string, sessionToken: string) =>
    request(`/api/v1/evaluations/${evaluationId}/conversation`, {}, sessionToken),
  debugLlm: () => {
    if (!ADMIN_API_KEY) {
      throw new Error('VITE_ADMIN_API_KEY is not configured');
    }
    return request('/api/v1/debug/llm', { headers: { 'X-Admin-Key': ADMIN_API_KEY } });
  },
};
