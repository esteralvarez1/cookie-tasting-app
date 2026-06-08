import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAdminAuth } from '../auth/useAdminAuth';
import { fetchHealth, fetchLlmProbe, AdminAuthError } from '../services/api';
import type { HealthStatus } from '../types';

export default function HealthPage() {
  const [status, setStatus] = useState<HealthStatus>('idle');
  const [data, setData] = useState<unknown>(null);
  const [errorMsg, setErrorMsg] = useState('');

  const [llmStatus, setLlmStatus] = useState<HealthStatus>('idle');
  const [llmData, setLlmData] = useState<unknown>(null);
  const [llmErrorMsg, setLlmErrorMsg] = useState('');

  const { getKey, logout } = useAdminAuth();
  const navigate = useNavigate();

  async function handleCheck() {
    const key = getKey();
    if (!key) {
      navigate('/admin/login', { replace: true });
      return;
    }
    setStatus('loading');
    setErrorMsg('');
    setData(null);
    try {
      const result = await fetchHealth(key);
      setData(result);
      setStatus('ok');
    } catch (err) {
      if (err instanceof AdminAuthError) {
        logout();
        navigate('/admin/login', { replace: true });
        return;
      }
      setErrorMsg(err instanceof Error ? err.message : 'Error desconocido');
      setStatus('error');
    }
  }

  async function handleLlmCheck() {
    const key = getKey();
    if (!key) {
      navigate('/admin/login', { replace: true });
      return;
    }
    setLlmStatus('loading');
    setLlmErrorMsg('');
    setLlmData(null);
    try {
      const result = await fetchLlmProbe(key);
      setLlmData(result);
      const payload = result as { data?: { effective_analyzer?: string } };
      setLlmStatus(payload.data?.effective_analyzer === 'llm' ? 'ok' : 'error');
    } catch (err) {
      if (err instanceof AdminAuthError) {
        logout();
        navigate('/admin/login', { replace: true });
        return;
      }
      setLlmErrorMsg(err instanceof Error ? err.message : 'Error desconocido');
      setLlmStatus('error');
    }
  }

  return (
    <div className="admin-page">
      <h2>Healthcheck</h2>
      <p className="admin-health-description">
        Comprueba que el backend está operativo y responde correctamente.
      </p>
      <button
        className="admin-btn-primary"
        onClick={handleCheck}
        disabled={status === 'loading'}
      >
        {status === 'loading' ? 'Comprobando…' : 'Lanzar comprobación'}
      </button>

      {(status === 'ok' || status === 'error') && (
        <div className="admin-health-result">
          <span className={`admin-status-indicator ${status}`}>
            {status === 'ok' ? 'OK' : 'ERROR'}
          </span>
          {status === 'ok' && data !== null && (
            <pre>{JSON.stringify(data, null, 2)}</pre>
          )}
          {status === 'error' && <p className="admin-health-error-msg">{errorMsg}</p>}
        </div>
      )}

      <p className="admin-health-description" style={{ marginTop: '2rem' }}>
        Realiza una llamada real al analizador LLM configurado para comprobar que responde correctamente.
      </p>
      <button
        className="admin-btn-secondary"
        onClick={handleLlmCheck}
        disabled={llmStatus === 'loading'}
      >
        {llmStatus === 'loading' ? 'Comprobando LLM…' : 'Comprobar LLM real'}
      </button>

      {(llmStatus === 'ok' || llmStatus === 'error') && (
        <div className="admin-health-result">
          <span className={`admin-status-indicator ${llmStatus}`}>
            {llmStatus === 'ok' ? 'LLM OK — analizador real' : 'LLM NO DISPONIBLE — revisa configuración'}
          </span>
          {llmData !== null && (
            <pre>{JSON.stringify(llmData, null, 2)}</pre>
          )}
          {llmStatus === 'error' && llmErrorMsg && (
            <p className="admin-health-error-msg">{llmErrorMsg}</p>
          )}
        </div>
      )}
    </div>
  );
}
