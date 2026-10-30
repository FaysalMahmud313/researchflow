import { Bell, CheckSquare, FileText, FolderKanban, Mail } from 'lucide-react';
import { href, useApp, useLoad } from '../lib/app';
import { timeAgo } from '../lib/text';
import { Avatar, EmptyState, SkeletonRows, StatusBadge } from '../components/ui';

interface Overview {
  counts: { projects: number; papers: number; open_tasks: number; unread_notifications: number; pending_invitations: number };
  recent_papers: { id: string; title: string; status: string; updated_at: string; last_editor_name: string; project_title: string }[];
  my_tasks: { id: string; title: string; status: string; priority: string; due_date: string; project_id: string; project_title: string }[];
  activity: { id: string; actor_id: string; summary: string; created_at: string; actor_name: string; project_id: string; project_title: string }[];
}

export function OverviewPage() {
  const { user } = useApp();
  const { data, loading } = useLoad<Overview>('/me/overview');
  const c = data?.counts;
  const stats = [
    { label: 'Projects', value: c?.projects, icon: FolderKanban, to: '#/mine' },
    { label: 'Papers', value: c?.papers, icon: FileText, to: '#/papers' },
    { label: 'My open tasks', value: c?.open_tasks, icon: CheckSquare, to: '#/tasks' },
    { label: 'Unread notifications', value: c?.unread_notifications, icon: Bell, to: '#/notifications' },
  ];
  return (
    <div className="mx-auto h-full max-w-6xl space-y-5 overflow-y-auto px-4 py-6">
      <h1 className="text-lg font-semibold">Welcome back, {user?.full_name.split(' ').slice(-1)[0]}</h1>
      {(c?.pending_invitations ?? 0) > 0 && (
        <p className="flex items-center gap-2 rounded-lg border border-accent/30 bg-accent/5 px-3 py-2 text-sm">
          <Mail size={15} className="text-accent" /> You have {c?.pending_invitations} pending project invitation{c?.pending_invitations === 1 ? '' : 's'}. Open the bell to respond.
        </p>
      )}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {stats.map((s) => (
          <a key={s.label} href={s.to} className="card flex items-center gap-3 p-3 hover:border-accent/50">
            <s.icon size={18} className="text-accent" />
            <span>
              <span className="block text-lg font-semibold tabular-nums">{s.value ?? '–'}</span>
              <span className="block text-xs text-muted">{s.label}</span>
            </span>
          </a>
        ))}
      </div>
      {loading && !data && <SkeletonRows rows={5} />}
      {data && (
        <div className="grid gap-4 lg:grid-cols-2">
          <section className="card">
            <h2 className="border-b border-line px-3 py-2 text-sm font-semibold">Recently edited papers</h2>
            {data.recent_papers.length === 0 ? <EmptyState title="No papers yet">Create one from a project's Papers tab.</EmptyState> : (
              <ul className="divide-y divide-line">
                {data.recent_papers.map((p) => (
                  <li key={p.id}>
                    <a href={href({ name: 'workspace', manuscriptId: p.id })} className="flex items-center gap-3 px-3 py-2 hover:bg-raised">
                      <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium">{p.title}</span><span className="block truncate text-xs text-muted">{p.project_title} · {p.last_editor_name ? `${p.last_editor_name}, ` : ''}{timeAgo(p.updated_at)}</span></span>
                      <StatusBadge status={p.status} />
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="card">
            <h2 className="border-b border-line px-3 py-2 text-sm font-semibold">Assigned to me</h2>
            {data.my_tasks.length === 0 ? <EmptyState title="No open tasks assigned to you" /> : (
              <ul className="divide-y divide-line">
                {data.my_tasks.map((t) => (
                  <li key={t.id}>
                    <a href={href({ name: 'project', projectId: t.project_id, tab: 'tasks' })} className="flex items-center gap-3 px-3 py-2 hover:bg-raised">
                      <span className="min-w-0 flex-1"><span className="block truncate text-[13px]">{t.title}</span><span className="block text-xs text-muted">{t.project_title}{t.due_date ? ` · due ${t.due_date}` : ''}</span></span>
                      <span className="chip">{t.status.replace('_', ' ')}</span>
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="card lg:col-span-2">
            <h2 className="border-b border-line px-3 py-2 text-sm font-semibold">Recent activity</h2>
            {data.activity.length === 0 ? <EmptyState title="Nothing yet" /> : (
              <ul className="divide-y divide-line">
                {data.activity.map((a) => (
                  <li key={a.id} className="flex items-start gap-3 px-3 py-2 text-sm">
                    <Avatar name={a.actor_name} userId={a.actor_id} size={24} />
                    <span className="min-w-0 flex-1"><b className="font-medium">{a.actor_name}</b> <span className="text-muted">{a.summary}</span> <a className="text-xs text-faint hover:text-ink" href={href({ name: 'project', projectId: a.project_id, tab: 'activity' })}>· {a.project_title}</a></span>
                    <span className="shrink-0 text-xs text-faint">{timeAgo(a.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
