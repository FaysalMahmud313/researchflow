import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Bell, BookOpen, Check, CheckSquare, Database, FileCode2, FileText, FlaskConical, FolderKanban, LogOut, Menu, Monitor, Moon, Search, Settings, Sun, User, X, Code2,
} from 'lucide-react';
import { api } from '../services/apiClient';
import { ACCENTS, href, navigate, useApp, type Route } from '../lib/app';
import { timeAgo } from '../lib/text';
import { Avatar, Dropdown, ResearchSignalIcon, Spinner, useErrorToast } from './ui';

type Hit = { id: string; project_id: string; title?: string; [k: string]: unknown };
type SearchResults = Record<string, Hit[]>;

const CATEGORIES: { key: string; label: string; icon: JSX.Element; route(h: Hit): Route; detail(h: Hit): string }[] = [
  { key: 'projects', label: 'Projects', icon: <FolderKanban size={14} />, route: (h) => ({ name: 'project', projectId: h.id, tab: 'papers' }), detail: (h) => `${h.research_domain ?? ''} · ${h.publication_status ?? ''}` },
  { key: 'manuscripts', label: 'Papers', icon: <FileText size={14} />, route: (h) => (h.doc_kind === 'latex' ? { name: 'workspace', manuscriptId: h.id } : { name: 'project', projectId: h.project_id, tab: 'papers' }), detail: (h) => `${h.project_title ?? ''} · ${h.status ?? ''}` },
  { key: 'source_files', label: 'Source files', icon: <FileCode2 size={14} />, route: (h) => ({ name: 'workspace', manuscriptId: String(h.document_id), fileId: h.id }), detail: (h) => String(h.manuscript_title ?? '') },
  { key: 'files', label: 'Datasets & files', icon: <Database size={14} />, route: (h) => ({ name: 'project', projectId: h.project_id, tab: 'files' }), detail: (h) => `${h.folder ?? ''} · ${h.artifact_type ?? ''}` },
  { key: 'references', label: 'References', icon: <BookOpen size={14} />, route: (h) => ({ name: 'project', projectId: h.project_id, tab: 'references' }), detail: (h) => `${h.cite_key ?? ''} · ${h.authors ?? ''} ${h.year ?? ''}` },
  { key: 'tasks', label: 'Tasks', icon: <CheckSquare size={14} />, route: (h) => ({ name: 'project', projectId: h.project_id, tab: 'tasks' }), detail: (h) => `${h.status ?? ''} · ${h.priority ?? ''}` },
  { key: 'experiments', label: 'Experiments', icon: <FlaskConical size={14} />, route: (h) => ({ name: 'project', projectId: h.project_id, tab: 'experiments' }), detail: (h) => `${h.method_or_model ?? ''} · ${h.status ?? ''}` },
  { key: 'artifacts', label: 'Code & results', icon: <Code2 size={14} />, route: (h) => ({ name: 'project', projectId: h.project_id, tab: 'code' }), detail: (h) => `${h.artifact_type ?? ''} · ${h.language ?? ''}` },
  { key: 'members', label: 'People', icon: <User size={14} />, route: (h) => ({ name: 'project', projectId: h.project_id, tab: 'members' }), detail: (h) => `@${h.username ?? ''} · ${h.role ?? ''} in ${h.project_title ?? ''}` },
];

function GlobalSearch() {
  const [q, setQ] = useState('');
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<SearchResults | null>(null);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes(tag) && !(e.target as HTMLElement)?.isContentEditable) {
        e.preventDefault();
        input.current?.focus();
      }
    };
    const onDown = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    window.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDown);
    return () => {
      window.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onDown);
    };
  }, []);

  useEffect(() => {
    const term = q.trim();
    if (!term) {
      setResults(null);
      return;
    }
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      api
        .get<SearchResults>(`/search?q=${encodeURIComponent(term)}&limit=5`, ctrl.signal)
        .then((r) => {
          setResults(r);
          setActive(0);
        })
        .catch(() => undefined)
        .finally(() => !ctrl.signal.aborted && setLoading(false));
    }, 180);
    return () => {
      window.clearTimeout(timer);
      ctrl.abort();
    };
  }, [q]);

  const flat = useMemo(() => {
    if (!results) return [];
    return CATEGORIES.flatMap((c) => (results[c.key] ?? []).map((h) => ({ cat: c, hit: h })));
  }, [results]);

  const go = (i: number) => {
    const item = flat[i];
    if (!item) return;
    navigate(item.cat.route(item.hit));
    setOpen(false);
    setQ('');
    input.current?.blur();
  };

  let index = -1;
  return (
    <div ref={box} className="relative w-full max-w-md">
      <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
      <input
        ref={input}
        role="combobox"
        aria-expanded={open && Boolean(q)}
        aria-controls="global-search-results"
        aria-label="Search projects, papers, files, references, people"
        className="input pl-8 pr-14"
        placeholder="Search projects, papers, people…"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActive((a) => Math.min(a + 1, flat.length - 1));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, 0));
          } else if (e.key === 'Enter') {
            e.preventDefault();
            go(active);
          } else if (e.key === 'Escape') {
            setOpen(false);
            input.current?.blur();
          }
        }}
      />
      <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2">{loading ? <Spinner size={13} /> : <kbd className="kbd">/</kbd>}</span>
      {open && q.trim() && (
        <div id="global-search-results" role="listbox" className="absolute left-0 right-0 top-full z-50 mt-1 max-h-[70vh] overflow-y-auto rounded-lg border border-line bg-surface p-1 shadow-pop">
          {!results && <div className="px-3 py-2 text-sm text-muted">Searching…</div>}
          {results && flat.length === 0 && <div className="px-3 py-3 text-sm text-muted">No results for “{q.trim()}”.</div>}
          {results &&
            CATEGORIES.map((cat) => {
              const hits = results[cat.key] ?? [];
              if (!hits.length) return null;
              return (
                <div key={cat.key} className="py-1">
                  <div className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-faint">{cat.label}</div>
                  {hits.map((h) => {
                    index += 1;
                    const i = index;
                    return (
                      <a
                        key={`${cat.key}-${h.id}-${h.project_id}`}
                        role="option"
                        aria-selected={i === active}
                        href={href(cat.route(h))}
                        onMouseEnter={() => setActive(i)}
                        onClick={(e) => {
                          e.preventDefault();
                          go(i);
                        }}
                        className={`flex items-start gap-2 rounded-md px-2 py-1.5 ${i === active ? 'bg-accent/10' : ''}`}
                      >
                        <span className="mt-0.5 text-muted">{cat.key === 'members' ? <Avatar name={String(h.title ?? '')} userId={h.id} size={18} /> : cat.icon}</span>
                        <span className="min-w-0">
                          <span className="block truncate text-[13px] text-ink">{String(h.title ?? h.username ?? '')}</span>
                          <span className="block truncate text-[11px] text-muted">{cat.detail(h)}</span>
                        </span>
                      </a>
                    );
                  })}
                </div>
              );
            })}
        </div>
      )}
    </div>
  );
}

interface Notification { id: string; kind: string; title: string; message: string; is_read: number; created_at: string; project_id: string | null }
interface Invitation { id: string; project_id: string; project_title: string; role: string; invited_by_name: string; message: string }

function NotificationsMenu() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Notification[]>([]);
  const [invites, setInvites] = useState<Invitation[]>([]);
  const onError = useErrorToast();
  const { toast } = useApp();

  const load = () => {
    api.get<{ notifications: Notification[] }>('/notifications').then((r) => setItems(r.notifications)).catch(() => undefined);
    api.get<{ invitations: Invitation[] }>('/invitations').then((r) => setInvites(r.invitations)).catch(() => undefined);
  };
  useEffect(() => {
    load();
    const t = window.setInterval(load, 60000);
    return () => window.clearInterval(t);
  }, []);
  const unread = items.filter((n) => !n.is_read).length + invites.length;

  const respond = async (inv: Invitation, action: 'accept' | 'reject') => {
    try {
      await api.patch(`/invitations/${inv.id}`, { action });
      toast(action === 'accept' ? `Joined ${inv.project_title}` : 'Invitation declined', 'success');
      load();
      if (action === 'accept') navigate({ name: 'project', projectId: inv.project_id, tab: 'papers' });
    } catch (e) {
      onError(e);
    }
  };

  return (
    <Dropdown
      open={open}
      setOpen={setOpen}
      align="right"
      trigger={
        <button className="icon-btn relative" onClick={() => setOpen(!open)} aria-label={`Notifications${unread ? ` (${unread} unread)` : ''}`}>
          <Bell size={16} />
          {unread > 0 && <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-danger" />}
        </button>
      }
    >
      <div className="w-[340px] max-h-[60vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        {invites.map((inv) => (
          <div key={inv.id} className="border-b border-line p-2">
            <p className="text-[13px]"><b>{inv.invited_by_name}</b> invited you to <b>{inv.project_title}</b> as {inv.role}.</p>
            {inv.message && <p className="mt-0.5 text-xs text-muted">“{inv.message}”</p>}
            <div className="mt-1.5 flex gap-1.5">
              <button className="btn-primary px-2 py-1 text-xs" onClick={() => respond(inv, 'accept')}><Check size={12} /> Accept</button>
              <button className="btn-ghost px-2 py-1 text-xs" onClick={() => respond(inv, 'reject')}><X size={12} /> Decline</button>
            </div>
          </div>
        ))}
        {items.length === 0 && invites.length === 0 && <p className="p-3 text-sm text-muted">You're all caught up.</p>}
        {items.map((n) => (
          <button
            key={n.id}
            className={`menu-item flex-col items-start ${n.is_read ? 'opacity-70' : ''}`}
            onClick={() => {
              api.patch(`/notifications/${n.id}`, { is_read: true }).catch(() => undefined);
              setItems((all) => all.map((x) => (x.id === n.id ? { ...x, is_read: 1 } : x)));
              if (n.project_id) navigate({ name: 'project', projectId: n.project_id, tab: 'papers' });
              setOpen(false);
            }}
          >
            <span className="text-[13px] font-medium">{n.title}</span>
            <span className="text-xs text-muted">{n.message}</span>
            <span className="text-[11px] text-faint">{timeAgo(n.created_at)}</span>
          </button>
        ))}
      </div>
    </Dropdown>
  );
}

export function ThemeMenu() {
  const { theme, setTheme, accent, setAccent } = useApp();
  const [open, setOpen] = useState(false);
  const Icon = theme === 'dark' ? Moon : theme === 'light' ? Sun : Monitor;
  return (
    <Dropdown open={open} setOpen={setOpen} align="right" trigger={<button className="icon-btn" onClick={() => setOpen(!open)} aria-label="Appearance"><Icon size={16} /></button>}>
      {([['light', Sun, 'Light'], ['dark', Moon, 'Dark'], ['system', Monitor, 'System']] as const).map(([mode, I, label]) => (
        <button key={mode} className="menu-item" onClick={() => setTheme(mode)}>
          <I size={14} /> {label} {theme === mode && <Check size={14} className="ml-auto text-accent" />}
        </button>
      ))}
      <div className="my-1 border-t border-line" />
      <div className="flex gap-1.5 px-2 py-1.5" onClick={(e) => e.stopPropagation()}>
        {ACCENTS.map((a) => (
          <button
            key={a.id}
            aria-label={`${a.name} accent`}
            title={a.name}
            onClick={() => setAccent(a.id)}
            className={`h-5 w-5 rounded-full ${accent === a.id ? 'ring-2 ring-offset-2 ring-offset-surface' : ''}`}
            style={{ background: a.hex, ['--tw-ring-color' as string]: a.hex }}
          />
        ))}
      </div>
    </Dropdown>
  );
}

export function TopNav({ compact, onMenu }: { compact?: boolean; onMenu(): void }) {
  const { user, logout } = useApp();
  const [menu, setMenu] = useState(false);
  return (
    <header className={`relative z-50 flex shrink-0 items-center gap-3 border-b border-line bg-surface px-3 ${compact ? 'h-11' : 'h-12'}`}>
      <button className={`icon-btn ${compact ? '' : 'md:hidden'}`} onClick={onMenu} aria-label="Navigation menu"><Menu size={17} /></button>
      <a href="#/overview" className="flex items-center gap-1.5 font-semibold text-ink">
        <ResearchSignalIcon className="h-5 w-5 text-accent" />
        <span className="hidden sm:inline">ResearchFlow</span>
      </a>
      <div className="flex flex-1 justify-center"><GlobalSearch /></div>
      <NotificationsMenu />
      <ThemeMenu />
      <Dropdown
        open={menu}
        setOpen={setMenu}
        align="right"
        trigger={<button onClick={() => setMenu(!menu)} aria-label="Account menu" className="rounded-full"><Avatar name={user?.full_name ?? '?'} userId={user?.id} version={user?.avatar_version ?? ''} size={28} /></button>}
      >
        <div className="flex items-center gap-2.5 px-2 py-2">
          <Avatar name={user?.full_name ?? '?'} userId={user?.id} version={user?.avatar_version ?? ''} size={36} />
          <span className="min-w-0">
            <span className="block truncate text-[13px] font-medium text-ink">{user?.full_name}</span>
            <span className="block truncate text-xs text-muted">@{user?.username}</span>
          </span>
        </div>
        <div className="my-1 border-t border-line" />
        <a className="menu-item" href="#/settings"><Settings size={14} /> Settings</a>
        <button className="menu-item" onClick={logout}><LogOut size={14} /> Sign out</button>
      </Dropdown>
    </header>
  );
}
