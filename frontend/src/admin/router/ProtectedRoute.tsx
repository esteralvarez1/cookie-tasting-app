import { Navigate } from 'react-router-dom';

type Props = { children: React.ReactNode };

export default function ProtectedRoute({ children }: Props) {
  const isAuthenticated = !!sessionStorage.getItem('admin_api_key');
  if (!isAuthenticated) return <Navigate to="/admin/login" replace />;
  return <>{children}</>;
}
