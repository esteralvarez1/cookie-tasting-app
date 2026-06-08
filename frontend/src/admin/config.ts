const BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

export const ADMIN_CONFIG = {
  apiBase: BASE,
  adminHeaderName: import.meta.env.VITE_ADMIN_HEADER_NAME || 'X-Admin-Key',
  endpoints: {
    health: `${BASE}/api/v1/health`,
    llmProbe: `${BASE}/api/v1/debug/llm/probe`,
    tastingSessions: `${BASE}/api/v1/tasting-sessions`,
    exportConversations: `${BASE}/api/v1/export/conversations`,
    exportUserResponses: `${BASE}/api/v1/export/user-responses`,
    exportStructured: `${BASE}/api/v1/export/structured`,
  },
} as const;
