import { NavLink, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { useAdminAuth } from './auth/useAdminAuth';
import LoginPage from './pages/LoginPage';
import SessionListPage from './pages/SessionListPage';
import TastingSessionPage from './pages/TastingSessionPage';
import ExportPage from './pages/ExportPage';
import HealthPage from './pages/HealthPage';
import ProtectedRoute from './router/ProtectedRoute';
import './admin.css';

export default function AdminShell() {
  const { logout, isAuthenticated } = useAdminAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate('/admin/login', { replace: true });
  }

  const authenticated = isAuthenticated();

  return (
    <div className="admin-shell">
      {authenticated && (
        <nav className="admin-nav">
          <span className="admin-nav-brand">Admin · Cookie Tasting</span>
          <NavLink
            to="/admin/sessions"
            end={false}
            className={({ isActive }) => (isActive ? 'admin-nav-link active' : 'admin-nav-link')}
          >
            Sesiones
          </NavLink>
          <NavLink
            to="/admin/export"
            className={({ isActive }) => (isActive ? 'admin-nav-link active' : 'admin-nav-link')}
          >
            Exportaciones
          </NavLink>
          <NavLink
            to="/admin/health"
            className={({ isActive }) => (isActive ? 'admin-nav-link active' : 'admin-nav-link')}
          >
            Healthcheck
          </NavLink>
          <button className="admin-nav-logout" onClick={handleLogout}>
            Cerrar sesión
          </button>
        </nav>
      )}
      <main className="admin-main">
        <Routes>
          <Route path="login" element={<LoginPage />} />
          <Route
            path="sessions"
            element={
              <ProtectedRoute>
                <SessionListPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="sessions/new"
            element={
              <ProtectedRoute>
                <TastingSessionPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="export"
            element={
              <ProtectedRoute>
                <ExportPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="health"
            element={
              <ProtectedRoute>
                <HealthPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="*"
            element={<Navigate to={authenticated ? '/admin/sessions' : '/admin/login'} replace />}
          />
        </Routes>
      </main>
    </div>
  );
}
