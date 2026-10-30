import { Bell, BookOpen, CheckSquare, Code2, Database, FileText, FlaskConical, FolderKanban, LayoutDashboard, Settings, Users } from 'lucide-react';
import { href, type Route, type Section } from '../lib/app';

const ITEMS: { section: Section; label: string; icon: typeof Bell }[] = [
  { section: 'overview', label: 'Overview', icon: LayoutDashboard },
  { section: 'mine', label: 'My Projects', icon: FolderKanban },
  { section: 'shared', label: 'Shared With Me', icon: Users },
  { section: 'papers', label: 'Papers & Drafts', icon: FileText },
  { section: 'files', label: 'Files & Datasets', icon: Database },
  { section: 'code', label: 'Code & Results', icon: Code2 },
  { section: 'references', label: 'Literature & References', icon: BookOpen },
  { section: 'experiments', label: 'Experiments', icon: FlaskConical },
  { section: 'tasks', label: 'Tasks', icon: CheckSquare },
  { section: 'notifications', label: 'Notifications', icon: Bell },
  { section: 'settings', label: 'Account & Settings', icon: Settings },
];

export function Sidebar({ route, open, onNavigate }: { route: Route; open: boolean; onNavigate(): void }) {
  const active = route.name === 'section' ? route.section : route.name === 'project' ? 'mine' : 'papers';
  return (
    <nav
      aria-label="Main"
      className={`${open ? 'fixed inset-y-0 left-0 z-40 flex w-60 pt-12 shadow-pop' : 'hidden'} flex-col border-r border-line bg-surface md:static md:z-auto md:flex md:w-56 md:pt-0 md:shadow-none`}
    >
      <ul className="flex-1 space-y-0.5 overflow-y-auto p-2">
        {ITEMS.map((it) => {
          const isActive = active === it.section;
          return (
            <li key={it.section}>
              <a
                href={href({ name: 'section', section: it.section })}
                onClick={onNavigate}
                aria-current={isActive ? 'page' : undefined}
                className={`flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] ${isActive ? 'bg-accent/10 font-medium text-ink' : 'text-muted hover:bg-raised hover:text-ink'}`}
              >
                <it.icon size={15} className={isActive ? 'text-accent' : ''} />
                {it.label}
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
