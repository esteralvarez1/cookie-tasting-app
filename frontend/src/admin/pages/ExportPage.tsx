import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAdminAuth } from '../auth/useAdminAuth';
import { fetchExport, fetchTastingSessions, AdminAuthError } from '../services/api';
import { triggerDownload, buildFallbackFilename } from '../utils/download';
import { ADMIN_CONFIG } from '../config';
import type { ExportFormat, BlockState, BlockConfig, TastingSessionConfig } from '../types';

const BLOCK_CONFIGS: BlockConfig[] = [
  {
    id: 'conversations',
    title: 'Conversación completa',
    description: 'Historial completo de turnos (usuario y bot) de todas las sesiones.',
    endpoint: ADMIN_CONFIG.endpoints.exportConversations,
    formats: ['csv', 'json'],
    defaultFormat: 'csv',
  },
  {
    id: 'user-responses',
    title: 'Respuestas del usuario',
    description: 'Únicamente los turnos del participante, sin mensajes del bot.',
    endpoint: ADMIN_CONFIG.endpoints.exportUserResponses,
    formats: ['csv', 'json'],
    defaultFormat: 'csv',
  },
  {
    id: 'structured',
    title: 'Clasificación estructurada',
    description: 'Análisis por modalidad con cabecera canónica de 18 columnas.',
    endpoint: ADMIN_CONFIG.endpoints.exportStructured,
    formats: ['csv', 'json', 'xlsx'],
    defaultFormat: 'xlsx',
  },
];

function initialBlockState(defaultFormat: ExportFormat): BlockState {
  return {
    tastingSessionConfigId: '',
    sessionId: '',
    participantCode: '',
    format: defaultFormat,
    loading: false,
    error: '',
    success: '',
  };
}

function initBlocks(): Record<string, BlockState> {
  return Object.fromEntries(BLOCK_CONFIGS.map((b) => [b.id, initialBlockState(b.defaultFormat)]));
}

export default function ExportPage() {
  const [blocks, setBlocks] = useState<Record<string, BlockState>>(initBlocks);
  const [tastingSessions, setTastingSessions] = useState<TastingSessionConfig[]>([]);
  const { getKey, logout } = useAdminAuth();
  const navigate = useNavigate();

  useEffect(() => {
    const key = getKey();
    if (!key) return;
    fetchTastingSessions(key).then(setTastingSessions).catch(() => {/* silent: dropdown stays empty */});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function updateBlock(id: string, patch: Partial<BlockState>) {
    setBlocks((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  }

  async function handleDownload(config: BlockConfig) {
    const key = getKey();
    if (!key) {
      navigate('/admin/login', { replace: true });
      return;
    }

    const block = blocks[config.id];
    updateBlock(config.id, { loading: true, error: '', success: '' });

    const params: Record<string, string> = { format: block.format };
    if (block.tastingSessionConfigId) params.tasting_session_config_id = block.tastingSessionConfigId;
    if (block.sessionId.trim()) params.session_id = block.sessionId.trim();
    if (block.participantCode.trim()) params.participant_code = block.participantCode.trim();

    try {
      const response = await fetchExport(config.endpoint, key, params);
      // The backend sets the authoritative filename via Content-Disposition.
      await triggerDownload(response, buildFallbackFilename(config.id, block.format));
      updateBlock(config.id, { loading: false, success: 'Archivo descargado correctamente.' });
    } catch (err) {
      if (err instanceof AdminAuthError) {
        logout();
        navigate('/admin/login', { replace: true });
        return;
      }
      updateBlock(config.id, {
        loading: false,
        error: err instanceof Error ? err.message : 'Error en la descarga.',
      });
    }
  }

  return (
    <div className="admin-page">
      <h2>Exportaciones</h2>
      {BLOCK_CONFIGS.map((config) => {
        const block = blocks[config.id];
        return (
          <div key={config.id} className="admin-export-block">
            <h3>{config.title}</h3>
            <p className="admin-export-description">{config.description}</p>
            <div className="admin-export-filters">
              <div className="admin-field">
                <label>Sesión de cata <span className="admin-optional">(opcional)</span></label>
                <select
                  value={block.tastingSessionConfigId}
                  onChange={(e) => updateBlock(config.id, { tastingSessionConfigId: e.target.value, success: '' })}
                >
                  <option value="">Todas las sesiones</option>
                  {tastingSessions.map((s) => (
                    <option key={s.tasting_session_id} value={s.tasting_session_id}>
                      {s.title || `Sesión ${s.tasting_session_id.slice(0, 8)}`}
                      {s.status === 'CLOSED' ? ' (cerrada)' : ''}
                    </option>
                  ))}
                </select>
              </div>
              <div className="admin-field">
                <label>ID de sesión de participante <span className="admin-optional">(opcional)</span></label>
                <input
                  type="text"
                  value={block.sessionId}
                  onChange={(e) => updateBlock(config.id, { sessionId: e.target.value, success: '' })}
                  placeholder="Dejar vacío para todas"
                />
              </div>
              <div className="admin-field">
                <label>Código de participante <span className="admin-optional">(opcional)</span></label>
                <input
                  type="text"
                  value={block.participantCode}
                  onChange={(e) => updateBlock(config.id, { participantCode: e.target.value, success: '' })}
                  placeholder="Dejar vacío para todos"
                />
              </div>
              <div className="admin-field">
                <label>Formato</label>
                <select
                  value={block.format}
                  onChange={(e) =>
                    updateBlock(config.id, { format: e.target.value as ExportFormat, success: '' })
                  }
                >
                  {config.formats.map((f) => (
                    <option key={f} value={f}>
                      {f.toUpperCase()}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="admin-export-actions">
              <button
                className="admin-btn-primary"
                disabled={block.loading}
                onClick={() => handleDownload(config)}
              >
                {block.loading ? 'Descargando…' : 'Descargar'}
              </button>
              {block.error && <span className="admin-inline-error">{block.error}</span>}
              {block.success && <span className="admin-inline-success">{block.success}</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
