import { useMemo, useState } from 'react';
import { FolderKanban, LayoutGrid, List, Plus, Search } from 'lucide-react';
import { api } from '../services/apiClient';
import { href, navigate, useLoad } from '../lib/app';
import { timeAgo } from '../lib/text';
import { PUBLICATION_STATUSES, type Project } from '../types';
import { Avatar, EmptyState, Modal, RoleBadge, SkeletonRows, Spinner, StatusBadge, useErrorToast } from '../components/ui';

const UPDATED_WINDOWS: Record<string, number> = { '7d': 7, '30d': 30, '90d': 90 };

function MemberStack({ project }: { project: Project }) {
  const members = project.members ?? [];
  return (
    <span className="flex items-center" title={members.map((m) => m.full_name).join(', ')}>
      <span className="flex -space-x-1.5">{members.slice(0, 4).map((m) => <Avatar key={m.username} name={m.full_name} userId={m.user_id} size={22} />)}</span>
      <span className="ml-1.5 text-[11px] text-muted">{project.member_count}</span>
    </span>
  );
}

export function ProjectsPage({ mode }: { mode: 'mine' | 'shared' }) {
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [activity, setActivity] = useState('');
  const [domain, setDomain] = useState('');
  const [role, setRole] = useState('');
  const [updated, setUpdated] = useState('');
  const [layout, setLayout] = useState<'grid' | 'list'>(() => {
    try {
      return (localStorage.getItem('rf_projects_layout') as 'grid' | 'list') || 'grid';
    } catch {
      return 'grid';
    }
  });
  const [creating, setCreating] = useState(false);

  const params = new URLSearchParams();
  if (q.trim()) params.set('q', q.trim());
  if (status) params.set('publication_status', status);
  if (activity) params.set('status', activity);
  if (role) params.set('role', role);
  if (domain) params.set('domain', domain);
  const { data, loading, error, reload } = useLoad<{ projects: Project[] }>(`/projects?${params.toString()}`);
  const all = useLoad<{ projects: Project[] }>('/projects');
  const domains = useMemo(() => Array.from(new Set((all.data?.projects ?? []).map((p) => p.research_domain))).sort(), [all.data]);

  const projects = (data?.projects ?? []).filter((p) => {
    if (mode === 'mine' ? p.my_role !== 'owner' : p.my_role === 'owner') return false;
    if (!updated) return true;
    return Date.now() - new Date(p.updated_at).getTime() < UPDATED_WINDOWS[updated] * 86400000;
  });
  const filtered = Boolean(q || status || activity || role || domain || updated);

  const toggleLayout = (l: 'grid' | 'list') => {
    setLayout(l);
    try {
      localStorage.setItem('rf_projects_layout', l);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="mx-auto h-full max-w-6xl overflow-y-auto px-4 py-6">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <h1 className="mr-auto text-lg font-semibold">{mode === 'mine' ? 'My Projects' : 'Shared With Me'}</h1>
        {mode === 'mine' && <button className="btn-primary" onClick={() => setCreating(true)}><Plus size={15} /> New project</button>}
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
          <input className="input pl-8" placeholder="Search by project or member name" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter projects" />
        </div>
        <select className="input w-auto" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Publication status">
          <option value="">Any publication status</option>
          {PUBLICATION_STATUSES.map((s) => <option key={s}>{s}</option>)}
        </select>
        <select className="input w-auto" value={activity} onChange={(e) => setActivity(e.target.value)} aria-label="Activity status">
          <option value="">Any activity</option>
          <option value="planning">Planning</option><option value="active">Active</option><option value="completed">Completed</option><option value="archived">Archived</option>
        </select>
        <select className="input w-auto" value={domain} onChange={(e) => setDomain(e.target.value)} aria-label="Category">
          <option value="">All categories</option>
          {domains.map((d) => <option key={d}>{d}</option>)}
        </select>
        {mode === 'shared' && (
          <select className="input w-auto" value={role} onChange={(e) => setRole(e.target.value)} aria-label="My role">
            <option value="">Any role</option>
            {['editor', 'reviewer', 'viewer'].map((r) => <option key={r} value={r}>{r[0].toUpperCase() + r.slice(1)}</option>)}
          </select>
        )}
        <select className="input w-auto" value={updated} onChange={(e) => setUpdated(e.target.value)} aria-label="Updated">
          <option value="">Any time</option><option value="7d">Updated in 7 days</option><option value="30d">Updated in 30 days</option><option value="90d">Updated in 90 days</option>
        </select>
        <div className="flex rounded-md border border-line">
          <button className={`icon-btn rounded-none ${layout === 'grid' ? 'bg-raised text-ink' : ''}`} onClick={() => toggleLayout('grid')} aria-label="Grid view"><LayoutGrid size={15} /></button>
          <button className={`icon-btn rounded-none ${layout === 'list' ? 'bg-raised text-ink' : ''}`} onClick={() => toggleLayout('list')} aria-label="Table view"><List size={15} /></button>
        </div>
      </div>

      {loading && !data && <SkeletonRows rows={5} />}
      {error && <p className="text-sm text-danger">{error}</p>}
      {data && projects.length === 0 && (
        <div className="card">
          <EmptyState icon={<FolderKanban size={28} />} title={filtered ? 'No projects match these filters' : mode === 'mine' ? 'You have not created a project yet' : 'Nothing shared with you yet'}
            action={mode === 'mine' && !filtered ? <button className="btn-primary mt-2" onClick={() => setCreating(true)}><Plus size={14} /> Create a project</button> : undefined}>
            {mode === 'shared' && !filtered ? 'Projects you are invited to appear here once you accept the invitation.' : undefined}
          </EmptyState>
        </div>
      )}

      {projects.length > 0 && layout === 'grid' && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <div key={p.id} className="card flex flex-col gap-2 p-3">
              <div className="flex items-start justify-between gap-2">
                <h2 className="line-clamp-2 font-medium leading-snug">{p.title}</h2>
                <RoleBadge role={p.my_role} />
              </div>
              <p className="line-clamp-2 text-xs text-muted">{p.description || p.research_domain}</p>
              <div className="flex flex-wrap items-center gap-2"><StatusBadge status={p.publication_status} /><span className="chip capitalize">{p.status}</span></div>
              <div className="mt-auto flex items-center gap-2 pt-1 text-[11px] text-muted">
                <MemberStack project={p} />
                <span className="ml-auto truncate">{p.last_editor_name ? `${p.last_editor_name}, ` : ''}{timeAgo(p.last_edited_at || p.updated_at)}</span>
              </div>
              <a href={href({ name: 'project', projectId: p.id, tab: 'papers' })} className="btn-outline justify-center">Open project</a>
            </div>
          ))}
        </div>
      )}
      {projects.length > 0 && layout === 'list' && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted"><tr className="border-b border-line"><th className="px-3 py-2 font-medium">Project</th><th className="px-2 font-medium">Publication status</th><th className="px-2 font-medium">Members</th><th className="px-2 font-medium">My role</th><th className="px-2 font-medium">Last editor</th><th className="px-2 font-medium">Updated</th><th /></tr></thead>
            <tbody className="divide-y divide-line">
              {projects.map((p) => (
                <tr key={p.id} className="hover:bg-raised/60">
                  <td className="px-3 py-2"><span className="block font-medium">{p.title}</span><span className="text-xs text-muted">{p.research_domain}</span></td>
                  <td className="px-2"><StatusBadge status={p.publication_status} /></td>
                  <td className="px-2"><MemberStack project={p} /></td>
                  <td className="px-2"><RoleBadge role={p.my_role} /></td>
                  <td className="px-2 text-xs text-muted">{p.last_editor_name || '—'}</td>
                  <td className="px-2 text-xs text-muted">{timeAgo(p.last_edited_at || p.updated_at)}</td>
                  <td className="px-2"><a className="btn-outline px-2 py-1 text-xs" href={href({ name: 'project', projectId: p.id, tab: 'papers' })}>Open</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <CreateProjectModal open={creating} onClose={() => setCreating(false)} onCreated={(id) => { reload(); navigate({ name: 'project', projectId: id, tab: 'papers' }); }} />
    </div>
  );
}

function CreateProjectModal({ open, onClose, onCreated }: { open: boolean; onClose(): void; onCreated(id: string): void }) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [domain, setDomain] = useState('Computer Science & AI');
  const [busy, setBusy] = useState(false);
  const onError = useErrorToast();
  const submit = async () => {
    setBusy(true);
    try {
      const res = await api.post<{ id: string }>('/projects', { title, description, research_domain: domain });
      onClose();
      setTitle('');
      setDescription('');
      onCreated(res.id);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onClose={onClose} title="New project"
      footer={<><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={busy || title.trim().length < 3} onClick={submit}>{busy && <Spinner size={14} />} Create</button></>}>
      <div className="space-y-3">
        <label className="block"><span className="label">Title</span><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Diffusion models for climate downscaling" /></label>
        <label className="block"><span className="label">Category</span><input className="input" value={domain} onChange={(e) => setDomain(e.target.value)} /></label>
        <label className="block"><span className="label">Description (optional)</span><textarea className="input min-h-[80px]" value={description} onChange={(e) => setDescription(e.target.value)} /></label>
      </div>
    </Modal>
  );
}
