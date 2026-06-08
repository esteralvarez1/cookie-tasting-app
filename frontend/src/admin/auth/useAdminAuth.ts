import { useCallback } from 'react';

const STORAGE_KEY = 'admin_api_key';

export function useAdminAuth() {
  const getKey = useCallback((): string | null => sessionStorage.getItem(STORAGE_KEY), []);

  const login = useCallback((key: string): void => {
    sessionStorage.setItem(STORAGE_KEY, key);
  }, []);

  const logout = useCallback((): void => {
    sessionStorage.removeItem(STORAGE_KEY);
  }, []);

  const isAuthenticated = useCallback((): boolean => !!sessionStorage.getItem(STORAGE_KEY), []);

  return { getKey, login, logout, isAuthenticated };
}
