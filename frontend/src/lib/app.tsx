import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { resetAvatarCache } from './avatars';
import { api, onUnauthorized, setCsrfToken } from '../services/apiClient';
import type { AccentColor, SessionUser, ThemeMode } from '../types';

// ---------------------------------------------------------------------------
// Routing (hash based: no server configuration needed)
// ---------------------------------------------------------------------------
export type Section = 'overview' | 'mine' | 'shared' | 'papers' | 'files' | 'code' | 'references' | 'experiments' | 'tasks' | 'notifications' | 'settings';

const SECTIONS: Section[] = ['overview', 'mine', 'shared', 'papers', 'files', 'code', 'references', 'experiments', 'tasks', 'notifications', 'settings'];

export type Route =
  | { name: 'section'; section: Section }
  | { name: 'project'; projectId: string; tab: string }
  | { name: 'workspace'; manuscriptId: string; fileId?: string };

export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
  if (parts[0] === 'p' && parts[1]) return { name: 'project', projectId: parts[1], tab: parts[2] || 'papers' };
  if (parts[0] === 'm' && parts[1]) return { name: 'workspace', manuscriptId: parts[1], fileId: parts[2] };
  if (SECTIONS.includes(parts[0] as Section)) return { name: 'section', section: parts[0] as Section };
  return { name: 'section', section: 'overview' };
}

export function href(route: Route): string {
  switch (route.name) {
    case 'project':
      return `#/p/${encodeURIComponent(route.projectId)}/${route.tab}`;
    case 'workspace':
      return `#/m/${encodeURIComponent(route.manuscriptId)}${route.fileId ? `/${encodeURIComponent(route.fileId)}` : ''}`;
    default:
      return `#/${route.section}`;
  }
}

export function navigate(route: Route, replace = false): void {
  const target = href(route);
  if (replace) window.history.replaceState(null, '', target);
  else window.location.hash = target;
  if (replace) window.dispatchEvent(new HashChangeEvent('hashchange'));
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------
export const ACCENTS: { id: AccentColor; hex: string; name: string }[] = [
  { id: 'indigo', hex: '#4f46e5', name: 'Indigo' },
  { id: 'blue', hex: '#2563eb', name: 'Blue' },
  { id: 'violet', hex: '#7c3aed', name: 'Violet' },
  { id: 'teal', hex: '#0d9488', name: 'Teal' },
  { id: 'emerald', hex: '#059669', name: 'Emerald' },
  { id: 'rose', hex: '#e11d48', name: 'Rose' },
  { id: 'amber', hex: '#d97706', name: 'Amber' },
];

function readLocal<T extends string>(key: string, fallback: T): T {
  try {
    return (localStorage.getItem(key) as T) || fallback;
  } catch {
    return fallback;
  }
}

function writeLocal(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable (private mode) */
  }
}

// ---------------------------------------------------------------------------
// App context: session, theme, toasts
// ---------------------------------------------------------------------------
interface Toast {
  id: number;
  kind: 'success' | 'error' | 'info';
  text: string;
}

interface AppContextValue {
  user: SessionUser | null;
  loading: boolean;
  setSession(user: SessionUser | null, csrf: string | null): void;
  /** Update fields of the signed-in user (e.g. a new name or profile picture). */
  updateUser(patch: Partial<SessionUser>): void;
  logout(): Promise<void>;
  theme: ThemeMode;
  accent: AccentColor;
  isDark: boolean;
  setTheme(mode: ThemeMode): void;
  setAccent(accent: AccentColor): void;
  toast(text: string, kind?: Toast['kind']): void;
  toasts: Toast[];
  dismissToast(id: number): void;
}

const AppContext = createContext<AppContextValue | null>(null);

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('AppProvider missing');
  return ctx;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [theme, setThemeState] = useState<ThemeMode>(() => readLocal<ThemeMode>('rf_theme_mode', 'system'));
  const [accent, setAccentState] = useState<AccentColor>(() => readLocal<AccentColor>('rf_accent_color', 'indigo'));
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false);
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!mq) return;
    const fn = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener('change', fn);
    return () => mq.removeEventListener('change', fn);
  }, []);

  const isDark = theme === 'dark' || (theme === 'system' && systemDark);
  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark);
    document.documentElement.dataset.accent = accent;
  }, [isDark, accent]);

  const setSession = useCallback((u: SessionUser | null, csrf: string | null) => {
    setCsrfToken(csrf);
    setUser(u);
  }, []);

  useEffect(() => {
    api
      .get<{ user: SessionUser; csrf_token: string }>('/auth/me')
      .then((res) => setSession(res.user, res.csrf_token))
      .catch(() => setSession(null, null))
      .finally(() => setLoading(false));
    return onUnauthorized(() => setSession(null, null));
  }, [setSession]);

  // After any sign-in (page load or the login form), apply the theme saved on the server,
  // so the choice follows the researcher across devices.
  const userId = user?.id;
  useEffect(() => {
    if (!userId) return;
    api
      .get<{ profile: { theme_mode: ThemeMode; accent_color: AccentColor } }>('/users/me')
      .then((profile) => {
        setThemeState(profile.profile.theme_mode);
        setAccentState(profile.profile.accent_color);
        writeLocal('rf_theme_mode', profile.profile.theme_mode);
        writeLocal('rf_accent_color', profile.profile.accent_color);
      })
      .catch(() => undefined);
  }, [userId]);

  const persistPrefs = useCallback(
    (patch: { theme_mode?: ThemeMode; accent_color?: AccentColor }) => {
      if (user) api.patch('/users/me/preferences', patch).catch(() => undefined);
    },
    [user],
  );

  const toast = useCallback((text: string, kind: Toast['kind'] = 'info') => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, kind, text }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === 'error' ? 7000 : 3500);
  }, []);

  const value = useMemo<AppContextValue>(
    () => ({
      user,
      loading,
      setSession,
      updateUser: (patch) => setUser((u) => (u ? { ...u, ...patch } : u)),
      async logout() {
        await api.post('/auth/logout').catch(() => undefined);
        resetAvatarCache();
        setSession(null, null);
        navigate({ name: 'section', section: 'overview' });
      },
      theme,
      accent,
      isDark,
      setTheme(mode) {
        setThemeState(mode);
        writeLocal('rf_theme_mode', mode);
        persistPrefs({ theme_mode: mode });
      },
      setAccent(a) {
        setAccentState(a);
        writeLocal('rf_accent_color', a);
        persistPrefs({ accent_color: a });
      },
      toast,
      toasts,
      dismissToast: (id) => setToasts((t) => t.filter((x) => x.id !== id)),
    }),
    [user, loading, setSession, theme, accent, isDark, persistPrefs, toast, toasts],
  );
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

/** Small data-loading hook with abort-on-unmount and manual reload. */
export function useLoad<T>(path: string | null, deps: unknown[] = []): { data: T | null; error: string | null; loading: boolean; reload(): void; setData(d: T): void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (!path) return;
    const ctrl = new AbortController();
    setLoading(true);
    api
      .get<T>(path, ctrl.signal)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: Error) => e.name !== 'AbortError' && setError(e.message))
      .finally(() => !ctrl.signal.aborted && setLoading(false));
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, nonce, ...deps]);
  return { data, error, loading, reload: () => setNonce((n) => n + 1), setData };
}
