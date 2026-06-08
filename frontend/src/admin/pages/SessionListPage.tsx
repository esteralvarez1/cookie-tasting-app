import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAdminAuth } from '../auth/useAdminAuth';
import { fetchTastingSessions, closeTastingSession, deleteTastingSession, AdminAuthError } from '../services/api';
import type { TastingSessionConfig } from '../types';

export default function SessionListPage() {
  const [sessions, setSessions] = useState<TastingSessionConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [closingId, setClosingId] = useState<string | null>(null);
  const [closeError, setCloseError] = useState<Record<string, string>>({});
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<Record<string, string>>({});
  const { getKey, logout } = useAdminAuth();
  const navigate = useNavigate();

  function handleAuthError() {
    logout();
    navigate('/admin/login', { replace: true });
  }

  useEffect(() => {
    const key = getKey();
    if (!key) { handleAuthError(); return; }
    fetchTastingSessions(key)
      .then(setSessions)
      .catch((err) => {
        if (err instanceof AdminAuthError) { handleAuthError(); return; }
        setError(err instanceof Error ? err.message : 'No se pudieron cargar las sesiones.');
      })
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleClose(sessionId: string) {
    const key = getKey();
    if (!key) { handleAuthError(); return; }
    setClosingId(sessionId);
    setCloseError((prev) => ({ ...prev, [sessionId]: '' }));
    try {
      const updated = await closeTastingSession(key, sessionId);
      setSessions((prev) => prev.map((s) => s.tasting_session_id === sessionId ? updated : s));
    } catch (err) {
      if (err instanceof AdminAuthError) { handleAuthError(); return; }
      setCloseError((prev) => ({
        ...prev,
        [sessionId]: err instanceof Error ? err.message : 'No se pudo cerrar la sesión.',
      }));
    } finally {
      setClosingId(null);
    }
  }

  async function handleDelete(sessionId: string, title: string | null) {
    const label = title || 'Sin título';
    const confirmed = window.confirm(
      `¿Eliminar la sesión "${label}"?\n\nEsta acción es irreversible y eliminará permanentemente la sesión y todas las respuestas de los participantes asociadas.`,
    );
    if (!confirmed) return;
    const key = getKey();
    if (!key) { handleAuthError(); return; }
    setDeletingId(sessionId);
    setDeleteError((prev) => ({ ...prev, [sessionId]: '' }));
    try {
      await deleteTastingSession(key, sessionId);
      setSessions((prev) => prev.filter((s) => s.tasting_session_id !== sessionId));
    } catch (err) {
      if (err instanceof AdminAuthError) { handleAuthError(); return; }
      setDeleteError((prev) => ({
        ...prev,
        [sessionId]: err instanceof Error ? err.message : 'No se pudo eliminar la sesión.',
      }));
    } finally {
      setDeletingId(null);
    }
  }

  function buildParticipantUrl(token: string) {
    return `${window.location.origin}/?token=${token}`;
  }

  return (
    <div className="admin-page">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
        <h2 style={{ margin: 0 }}>Sesiones de cata</h2>
        <button className="admin-btn-primary" onClick={() => navigate('/admin/sessions/new')}>
          + Nueva sesión
        </button>
      </div>

      {error && <div className="admin-error">{error}</div>}

      {loading && <p style={{ color: '#666' }}>Cargando sesiones...</p>}

      {!loading && !error && sessions.length === 0 && (
        <div className="admin-export-block">
          <p style={{ color: '#666', margin: 0 }}>No hay sesiones creadas todavía.</p>
        </div>
      )}

      {sessions.map((s) => {
        const participantUrl = buildParticipantUrl(s.public_token);
        const isClosed = s.status === 'CLOSED';
        const isClosing = closingId === s.tasting_session_id;
        const isDeleting = deletingId === s.tasting_session_id;

        return (
          <div key={s.tasting_session_id} className="admin-export-block">
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.3rem' }}>
                  <h3 style={{ margin: 0, fontSize: '1.05rem' }}>
                    {s.title || <span style={{ color: '#999', fontStyle: 'italic' }}>Sin título</span>}
                  </h3>
                  <span className={`admin-status-indicator ${isClosed ? 'error' : 'ok'}`}>
                    {isClosed ? 'Cerrada' : 'Activa'}
                  </span>
                </div>

                <p className="admin-export-description" style={{ marginBottom: '0.75rem' }}>
                  {s.total_samples} muestra(s): {s.sample_codes.join(', ')}
                </p>

                <div className="admin-field" style={{ marginBottom: 0 }}>
                  <label>Enlace de participación</label>
                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <input
                      type="text"
                      readOnly
                      value={participantUrl}
                      onClick={(e) => (e.target as HTMLInputElement).select()}
                      style={{ flex: 1, minWidth: 0 }}
                    />
                    <button
                      className="admin-btn-secondary"
                      style={{ flexShrink: 0 }}
                      onClick={() => navigator.clipboard.writeText(participantUrl)}
                    >
                      Copiar
                    </button>
                  </div>
                </div>
              </div>

              <div style={{ flexShrink: 0, paddingTop: '0.15rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                <button
                  className="admin-btn-danger"
                  disabled={isClosed || isClosing || isDeleting}
                  onClick={() => handleClose(s.tasting_session_id)}
                >
                  {isClosing ? 'Cerrando...' : 'Cerrar sesión'}
                </button>
                <button
                  className="admin-btn-delete"
                  disabled={isDeleting || isClosing}
                  onClick={() => handleDelete(s.tasting_session_id, s.title ?? null)}
                >
                  {isDeleting ? 'Eliminando...' : 'Eliminar sesión'}
                </button>
              </div>
            </div>

            {closeError[s.tasting_session_id] && (
              <p className="admin-inline-error" style={{ marginTop: '0.5rem' }}>
                {closeError[s.tasting_session_id]}
              </p>
            )}
            {deleteError[s.tasting_session_id] && (
              <p className="admin-inline-error" style={{ marginTop: '0.5rem' }}>
                {deleteError[s.tasting_session_id]}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
