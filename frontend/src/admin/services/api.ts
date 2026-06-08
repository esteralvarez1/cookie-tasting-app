import { ADMIN_CONFIG } from '../config';
import type { CreatedTastingSession, TastingSessionConfig, TastingSessionCreate } from '../types';

export class AdminAuthError extends Error {
  constructor() {
    super('Credenciales no válidas o sesión expirada');
    this.name = 'AdminAuthError';
  }
}

async function adminFetch(
  url: string,
  key: string,
  params?: Record<string, string>,
): Promise<Response> {
  const fullUrl =
    params && Object.keys(params).length > 0
      ? `${url}?${new URLSearchParams(params)}`
      : url;

  const response = await fetch(fullUrl, {
    headers: { [ADMIN_CONFIG.adminHeaderName]: key },
  });

  if (response.status === 401 || response.status === 403) {
    throw new AdminAuthError();
  }

  return response;
}

export async function validateAdminKey(key: string): Promise<void> {
  const response = await fetch(ADMIN_CONFIG.endpoints.tastingSessions, {
    headers: { [ADMIN_CONFIG.adminHeaderName]: key },
  });
  if (response.status === 401 || response.status === 403) {
    throw new AdminAuthError();
  }
  if (!response.ok) {
    throw new Error(`Error ${response.status}: ${response.statusText}`);
  }
}

export async function fetchHealth(key: string): Promise<unknown> {
  const response = await adminFetch(ADMIN_CONFIG.endpoints.health, key);
  if (!response.ok) throw new Error(`Error ${response.status}: ${response.statusText}`);
  const isJson = response.headers.get('content-type')?.includes('application/json');
  return isJson ? response.json() : response.text();
}

export async function fetchLlmProbe(key: string): Promise<unknown> {
  const response = await fetch(ADMIN_CONFIG.endpoints.llmProbe, {
    method: 'POST',
    headers: { [ADMIN_CONFIG.adminHeaderName]: key },
  });
  if (response.status === 401 || response.status === 403) throw new AdminAuthError();
  if (!response.ok) throw new Error(`Error ${response.status}: ${response.statusText}`);
  return response.json();
}

export async function fetchTastingSessions(key: string): Promise<TastingSessionConfig[]> {
  const response = await adminFetch(ADMIN_CONFIG.endpoints.tastingSessions, key);
  if (!response.ok) {
    const isJson = response.headers.get('content-type')?.includes('application/json');
    const body = isJson ? await response.json() : await response.text();
    const detail = typeof body === 'string' ? body : ((body as Record<string, unknown>)?.detail ?? `Error ${response.status}`);
    throw new Error(String(detail));
  }
  const json = await response.json();
  return (json?.data ?? json) as TastingSessionConfig[];
}

export async function closeTastingSession(key: string, sessionId: string): Promise<TastingSessionConfig> {
  const response = await fetch(`${ADMIN_CONFIG.endpoints.tastingSessions}/${sessionId}/close`, {
    method: 'POST',
    headers: { [ADMIN_CONFIG.adminHeaderName]: key },
  });
  if (response.status === 401 || response.status === 403) throw new AdminAuthError();
  if (!response.ok) {
    const isJson = response.headers.get('content-type')?.includes('application/json');
    const body = isJson ? await response.json() : await response.text();
    const detail = typeof body === 'string' ? body : ((body as Record<string, unknown>)?.detail ?? `Error ${response.status}`);
    throw new Error(String(detail));
  }
  const json = await response.json();
  return (json?.data ?? json) as TastingSessionConfig;
}

export async function createTastingSession(key: string, data: TastingSessionCreate): Promise<CreatedTastingSession> {
  const response = await fetch(ADMIN_CONFIG.endpoints.tastingSessions, {
    method: 'POST',
    headers: {
      [ADMIN_CONFIG.adminHeaderName]: key,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
  });
  if (response.status === 401 || response.status === 403) throw new AdminAuthError();
  if (!response.ok) {
    const isJson = response.headers.get('content-type')?.includes('application/json');
    const body = isJson ? await response.json() : await response.text();
    const detail = typeof body === 'string' ? body : ((body as Record<string, unknown>)?.detail ?? `Error ${response.status}`);
    throw new Error(String(detail));
  }
  const json = await response.json();
  return (json?.data ?? json) as CreatedTastingSession;
}

export async function deleteTastingSession(key: string, sessionId: string): Promise<void> {
  const response = await fetch(`${ADMIN_CONFIG.endpoints.tastingSessions}/${sessionId}`, {
    method: 'DELETE',
    headers: { [ADMIN_CONFIG.adminHeaderName]: key },
  });
  if (response.status === 401 || response.status === 403) throw new AdminAuthError();
  if (!response.ok) {
    const isJson = response.headers.get('content-type')?.includes('application/json');
    const body = isJson ? await response.json() : await response.text();
    const detail = typeof body === 'string' ? body : ((body as Record<string, unknown>)?.detail ?? `Error ${response.status}`);
    throw new Error(String(detail));
  }
}

export async function fetchExport(
  endpoint: string,
  key: string,
  params: Record<string, string>,
): Promise<Response> {
  const response = await adminFetch(endpoint, key, params);
  if (!response.ok) {
    const isJson = response.headers.get('content-type')?.includes('application/json');
    const body = isJson ? await response.json() : await response.text();
    const detail = typeof body === 'string' ? body : ((body as Record<string, unknown>)?.detail ?? `Error ${response.status}`);
    throw new Error(String(detail));
  }
  return response;
}
