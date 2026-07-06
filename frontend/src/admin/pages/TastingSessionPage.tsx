import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAdminAuth } from '../auth/useAdminAuth';
import { createTastingSession, AdminAuthError } from '../services/api';
import type { CreatedTastingSession } from '../types';

export default function TastingSessionPage() {
  const [title, setTitle] = useState('');
  const [codesText, setCodesText] = useState('');
  const [finalRedirectUrl, setFinalRedirectUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [created, setCreated] = useState<CreatedTastingSession | null>(null);
  const { getKey, logout } = useAdminAuth();
  const navigate = useNavigate();

  const sampleCodes = codesText
    .split('\n')
    .map((c) => c.trim())
    .filter(Boolean);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const key = getKey();
    if (!key) { navigate('/admin/login', { replace: true }); return; }
    if (sampleCodes.length === 0) { setError('Introduce al menos un código de muestra.'); return; }
    setLoading(true);
    setError('');
    try {
      const data = await createTastingSession(key, {
        title: title.trim() || undefined,
        sample_codes: sampleCodes,
        final_redirect_url: finalRedirectUrl.trim() || undefined,
      });
      setCreated(data);
    } catch (err) {
      if (err instanceof AdminAuthError) { logout(); navigate('/admin/login', { replace: true }); return; }
      setError(err instanceof Error ? err.message : 'Error al crear la sesión.');
    } finally {
      setLoading(false);
    }
  }

  if (created) {
    const participantUrl = `${window.location.origin}/cata?token=${created.public_token}`;
    return (
      <div className="admin-page">
        <h2>Sesión creada</h2>
        <div className="admin-export-block">
          <h3>{created.title || 'Sin título'}</h3>
          <p className="admin-export-description">
            {created.total_samples} muestra(s): {created.sample_codes.join(', ')}
          </p>
          <div className="admin-field">
            <label>Enlace de participación</label>
            <input
              type="text"
              readOnly
              value={participantUrl}
              onClick={(e) => (e.target as HTMLInputElement).select()}
            />
          </div>
          {created.final_redirect_url && (
            <div className="admin-field" style={{ marginTop: '0.75rem' }}>
              <label>Enlace final configurado</label>
              <input
                type="text"
                readOnly
                value={created.final_redirect_url}
                onClick={(e) => (e.target as HTMLInputElement).select()}
              />
            </div>
          )}
          <div className="admin-export-actions" style={{ marginTop: '1rem' }}>
            <button
              className="admin-btn-primary"
              onClick={() => navigator.clipboard.writeText(participantUrl)}
            >
              Copiar enlace
            </button>
            <button
              className="admin-btn-secondary"
              onClick={() => { setCreated(null); setTitle(''); setCodesText(''); setFinalRedirectUrl(''); }}
            >
              Crear otra sesión
            </button>
            <button
              className="admin-btn-secondary"
              onClick={() => navigate('/admin/sessions')}
            >
              Ver todas las sesiones
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1.5rem' }}>
        <button type="button" className="admin-btn-secondary" onClick={() => navigate('/admin/sessions')}>
          ← Volver
        </button>
        <h2 style={{ margin: 0 }}>Nueva sesión de cata</h2>
      </div>
      <form className="admin-export-block" onSubmit={handleSubmit}>
        <div className="admin-field">
          <label>Título <span className="admin-optional">(opcional)</span></label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Ej: Cata ciega noviembre 2026"
          />
        </div>
        <div className="admin-field">
          <label>Códigos de muestra <span className="admin-optional">(uno por línea)</span></label>
          <textarea
            rows={5}
            value={codesText}
            onChange={(e) => { setCodesText(e.target.value); setError(''); }}
            placeholder={'G101\nG102\nG103'}
          />
          {sampleCodes.length > 0 && (
            <p className="admin-export-description" style={{ marginTop: '0.4rem', marginBottom: 0 }}>
              {sampleCodes.length} muestra(s): {sampleCodes.join(', ')}
            </p>
          )}
        </div>
        <div className="admin-field">
          <label>Enlace final <span className="admin-optional">(opcional)</span></label>
          <input
            type="url"
            value={finalRedirectUrl}
            onChange={(e) => { setFinalRedirectUrl(e.target.value); setError(''); }}
            placeholder="https://..."
          />
        </div>
        <div className="admin-export-actions" style={{ marginTop: '1.25rem' }}>
          <button
            type="submit"
            className="admin-btn-primary"
            disabled={loading || sampleCodes.length === 0}
          >
            {loading ? 'Creando...' : 'Crear sesión de cata'}
          </button>
          {error && <span className="admin-inline-error">{error}</span>}
        </div>
      </form>
    </div>
  );
}
