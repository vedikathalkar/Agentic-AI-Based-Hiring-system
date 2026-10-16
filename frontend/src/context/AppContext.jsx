import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { api, roleForPath, session } from '../api';

const AppContext = createContext(null);

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme === 'dark' ? 'dark' : 'light';
}

function initialTheme() {
  try {
    const saved = localStorage.getItem('hirelune_theme');
    if (saved === 'dark' || saved === 'light') return saved;
  } catch { /* storage unavailable */ }
  // Nothing saved yet: start in the dark look the home page uses.
  return 'dark';
}

export function AppProvider({ children }) {
  // The portal (candidate / hr / admin) is taken from the URL; each has its own saved session.
  const { pathname } = useLocation();
  const role = roleForPath(pathname);
  const [version, setVersion] = useState(0);        // bumped whenever a session is saved or cleared
  const user = useMemo(() => {
    void version;   // re-read storage after login/logout
    return session.token(role) ? session.user(role) : null;
  }, [role, version]);
  const [me, setMe] = useState(null);              // live data from /auth/me (credits, unread, verification)
  const [theme, setThemeState] = useState(initialTheme);
  const [toasts, setToasts] = useState([]);

  useEffect(() => { applyTheme(theme); }, [theme]);

  const refreshMe = useCallback(async () => {
    if (!session.token()) { setMe(null); return null; }
    const want = roleForPath();
    setMe((prev) => (prev && prev.role !== want ? null : prev));
    try {
      const data = await api.me();
      if (roleForPath() === want) setMe(data);
      return data;
    } catch { return null; }
  }, []);

  // On load, the account's saved theme wins over the local fallback.
  useEffect(() => {
    refreshMe().then((data) => {
      if (data?.theme === 'dark' || data?.theme === 'light') {
        setThemeState(data.theme);
        try { localStorage.setItem('hirelune_theme', data.theme); } catch { /* ignore */ }
      }
    });
  }, [refreshMe, role]);

  useEffect(() => {
    const onLogout = () => { setVersion((v) => v + 1); setMe(null); };
    window.addEventListener('hirelune:logout', onLogout);
    return () => window.removeEventListener('hirelune:logout', onLogout);
  }, []);

  const login = useCallback((data) => {
    session.save(data);
    setVersion((v) => v + 1);
    if (data.theme) setThemeState(data.theme);
    refreshMe();
  }, [refreshMe]);

  const logout = useCallback(async () => {
    try { await api.logout(); } catch { /* already expired */ }
    session.clear();
    setVersion((v) => v + 1);
    setMe(null);
  }, []);

  // Theme is stored on the account (server) when logged in, and locally as a fallback.
  const setTheme = useCallback(async (next) => {
    setThemeState(next);
    try { localStorage.setItem('hirelune_theme', next); } catch { /* ignore */ }
    if (session.token()) {
      try { await api.updateSettings({ theme: next }); } catch { /* keep local choice */ }
    }
  }, []);

  const toast = useCallback((message, tone = 'info') => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000);
  }, []);

  const value = useMemo(() => ({ user, me, refreshMe, login, logout, theme, setTheme, toast }),
    [user, me, refreshMe, login, logout, theme, setTheme, toast]);

  return (
    <AppContext.Provider value={value}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className={`toast toast-${t.tone}`}>{t.message}</div>)}
      </div>
    </AppContext.Provider>
  );
}

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp must be used inside AppProvider');
  return ctx;
}
