import { useState } from 'react';
import { CheckSquare, Plus } from 'lucide-react';
import { api } from '../../services/apiClient';
import { useLoad } from '../../lib/app';
import type { Project, TaskStatus } from '../../types';
import { Avatar, EmptyState, SkeletonRows, useErrorToast } from '../../components/ui';

interface Task { id: string; title: string; description: string; status: TaskStatus; priority: string; due_date: string; assignee_ids?: string[] }
interface Member { user_id: string; full_name: string }

const COLUMNS: { id: TaskStatus; label: string }[] = [
  { id: 'todo', label: 'To do' },
  { id: 'in_progress', label: 'In progress' },
  { id: 'in_review', label: 'In review' },
  { id: 'done', label: 'Done' },
];

export function TasksTab({ project }: { project: Project }) {
  const { data, loading, reload } = useLoad<{ tasks: Task[] }>(`/projects/${project.id}/tasks`);
  const members = useLoad<{ members: Member[] }>(`/projects/${project.id}/members`);
  const nameOf = (id: string) => members.data?.members.find((m) => m.user_id === id)?.full_name ?? 'Former member';
  const [title, setTitle] = useState('');
  const [priority, setPriority] = useState('medium');
  const onError = useErrorToast();
  const canWrite = project.my_role === 'owner' || project.my_role === 'editor';

  const add = async () => {
    if (title.trim().length < 2) return;
    try {
      await api.post(`/projects/${project.id}/tasks`, { title: title.trim(), priority });
      setTitle('');
      reload();
    } catch (e) {
      onError(e);
    }
  };

  return (
    <div className="space-y-3">
      {canWrite && (
        <div className="flex gap-2">
          <input className="input" placeholder="Add a task and press Enter" value={title} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} aria-label="New task" />
          <select className="input w-auto" value={priority} onChange={(e) => setPriority(e.target.value)} aria-label="Priority"><option>low</option><option>medium</option><option>high</option><option>urgent</option></select>
          <button className="btn-primary" onClick={add}><Plus size={14} /> Add</button>
        </div>
      )}
      {loading && !data && <SkeletonRows />}
      {data && data.tasks.length === 0 && <div className="card"><EmptyState icon={<CheckSquare size={26} />} title="No tasks" /></div>}
      {data && data.tasks.length > 0 && (
        <div className="grid gap-3 md:grid-cols-4">
          {COLUMNS.map((col) => (
            <div key={col.id} className="rounded-lg bg-raised/60 p-2">
              <h3 className="mb-2 px-1 text-xs font-semibold uppercase text-faint">{col.label} · {data.tasks.filter((t) => t.status === col.id).length}</h3>
              <div className="space-y-2">
                {data.tasks.filter((t) => t.status === col.id).map((t) => (
                  <div key={t.id} className="card p-2 text-sm">
                    <p className="font-medium">{t.title}</p>
                    <div className="mt-1 flex items-center justify-between text-xs text-muted">
                      <span className="flex items-center gap-2">
                        <span className={t.priority === 'urgent' || t.priority === 'high' ? 'text-danger' : ''}>{t.priority}</span>
                        {!!t.assignee_ids?.length && (
                          <span className="flex -space-x-1.5" aria-label={`Assigned to ${t.assignee_ids.map(nameOf).join(', ')}`}>
                            {t.assignee_ids.slice(0, 3).map((id) => <Avatar key={id} name={nameOf(id)} userId={id} size={20} />)}
                          </span>
                        )}
                      </span>
                      {canWrite && (
                        <select className="rounded border border-line bg-surface px-1 py-0.5 text-xs" value={t.status} aria-label={`Status of ${t.title}`}
                          onChange={(e) => api.patch(`/tasks/${t.id}`, { status: e.target.value }).then(reload).catch(onError)}>
                          {COLUMNS.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                        </select>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
