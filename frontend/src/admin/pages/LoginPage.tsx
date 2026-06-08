import { useState, FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAdminAuth } from '../auth/useAdminAuth';
import { validateAdminKey, AdminAuthError } from '../services/api';

export default function LoginPage() {
  const [key, setKey] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAdminAuth();
  const navigate = useNavigate();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!key.trim()) return;
    setLoading(true);
    setError('');
    try {
      await validateAdminKey(key.trim());
      login(key.trim());
      navigate('/admin/sessions', { replace: true });
    } catch (err) {
      if (err instanceof AdminAuthError) {
        setError('Clave de administrador incorrecta.');
      } else {
        setError('No se pudo conectar con el servidor.');
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="admin-login-page">
      <div className="admin-login-card">
        <h1>Panel de administración</h1>
        <p className="admin-subtitle">Cata conversacional de galletas</p>
        {error && <div className="admin-error">{error}</div>}
        <form onSubmit={handleSubmit}>
          <label htmlFor="admin-key">Clave de administrador</label>
          <input
            id="admin-key"
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="Introduce tu clave"
            autoComplete="current-password"
          />
          <button type="submit" disabled={loading || !key.trim()}>
            {loading ? 'Verificando…' : 'Entrar'}
          </button>
        </form>
      </div>
    </div>
  );
}
