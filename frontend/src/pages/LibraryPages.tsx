/** Cross-project lists for the sidebar sections. Each row links into its project. */
import { useEffect, useState, type ReactNode } from 'react';
import { BookOpen, CheckSquare, Code2, Copy, Database, Download, FileText, FlaskConical, Search } from 'lucide-react';
import { downloadFile } from '../services/apiClient';
import { href, useApp, useLoad } from '../lib/app';
import { formatBytes, timeAgo } from '../lib/text';
import { MANUSCRIPT_STATUSES } from '../types';
import { EmptyState, SkeletonRows, StatusBadge, useErrorToast } from '../components/ui';

function useDebounced(value: string, ms = 250): string {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

function PageShell({ title, hint, controls, children }: { title: string; hint?: string; controls?: ReactNode; children: ReactNode }) {
  return (
    <div className="mx-auto h-full max-w-6xl overflow-y-auto px-4 py-6">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <h1 className="mr-auto text-lg font-semibold">{title}</h1>
        {controls}
      </div>
      {hint && <p className="mb-4 text-xs text-muted">{hint}</p>}
      {children}
    </div>
  );
}

function SearchBox({ value, onChange, placeholder }: { value: string; onChange(v: string): void; placeholder: string }) {
  return (
    <div className="relative w-64 max-w-full">
      <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
      <input className="input pl-8" placeholder={placeholder} value={value} onChange={(e) => onChange(e.target.value)} aria-label={placeholder} />
    </div>
  );
}

export function PapersPage() {
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const dq = useDebounced(q);
  const params = new URLSearchParams();
  if (dq) params.set('q', dq);
  if (status) params.set('status', status);
  const { data, loading } = useLoad<{ manuscripts: { id: string; title: string; status: string; review_status: string; updated_at: string; last_editor_name: string; project_id: string; project_title: string; my_role: string }[] }>(`/me/manuscripts?${params}`);
  return (
    <PageShell title="Papers & Drafts" hint="LaTeX papers across all your projects. Create or import papers from a project's Papers tab."
      controls={<>
        <SearchBox value={q} onChange={setQ} placeholder="Search papers or projects" />
        <select className="input w-auto" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status"><option value="">All statuses</option>{MANUSCRIPT_STATUSES.map((s) => <option key={s}>{s}</option>)}</select>
      </>}>
      {loading && !data && <SkeletonRows />}
      {data && data.manuscripts.length === 0 && <div className="card"><EmptyState icon={<FileText size={26} />} title="No papers found" /></div>}
      {data && data.manuscripts.length > 0 && (
        <div className="card divide-y divide-line">
          {data.manuscripts.map((m) => (
            <a key={m.id} href={href({ name: 'workspace', manuscriptId: m.id })} className="flex flex-wrap items-center gap-3 px-3 py-2.5 hover:bg-raised">
              <FileText size={16} className="text-muted" />
              <span className="min-w-0 flex-1"><span className="block truncate font-medium">{m.title}</span><span className="block truncate text-xs text-muted">{m.project_title} · edited {timeAgo(m.updated_at)}{m.last_editor_name ? ` by ${m.last_editor_name}` : ''}</span></span>
              <StatusBadge status={m.status} />
              <span className="chip capitalize">{m.my_role}</span>
            </a>
          ))}
        </div>
      )}
    </PageShell>
  );
}

const FILE_TYPES = ['dataset', 'manuscript', 'code', 'notebook', 'figure', 'log', 'result', 'checkpoint'];

export function FilesPage() {
  const [q, setQ] = useState('');
  const [type, setType] = useState('');
  const dq = useDebounced(q);
  const params = new URLSearchParams();
  if (dq) params.set('q', dq);
  if (type) params.set('artifact_type', type);
  const { data, loading } = useLoad<{ files: { id: string; project_id: string; folder: string; original_name: string; size_bytes: number; artifact_type: string; updated_at: string; owner_name: string; project_title: string; current_version: number }[] }>(`/me/files?${params}`);
  const onError = useErrorToast();
  return (
    <PageShell title="Files & Datasets" hint="Every file you can access. Upload, rename, move and manage versions inside a project's Files & data tab."
      controls={<>
        <SearchBox value={q} onChange={setQ} placeholder="Search by file name" />
        <select className="input w-auto" value={type} onChange={(e) => setType(e.target.value)} aria-label="Type"><option value="">All types</option>{FILE_TYPES.map((t) => <option key={t}>{t}</option>)}</select>
      </>}>
      {loading && !data && <SkeletonRows />}
      {data && data.files.length === 0 && <div className="card"><EmptyState icon={<Database size={26} />} title="No files found" /></div>}
      {data && data.files.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted"><tr className="border-b border-line"><th className="px-3 py-2 font-medium">Name</th><th className="px-2 font-medium">Project</th><th className="px-2 font-medium">Type</th><th className="px-2 font-medium">Size</th><th className="px-2 font-medium">Uploaded by</th><th className="px-2 font-medium">Updated</th><th /></tr></thead>
            <tbody className="divide-y divide-line">
              {data.files.map((f) => (
                <tr key={f.id} className="hover:bg-raised/60">
                  <td className="px-3 py-2"><span className="block truncate font-medium">{f.original_name}</span><span className="text-xs text-muted">{f.folder}{f.current_version > 1 ? ` · v${f.current_version}` : ''}</span></td>
                  <td className="px-2 text-xs"><a className="hover:text-accent" href={href({ name: 'project', projectId: f.project_id, tab: 'files' })}>{f.project_title}</a></td>
                  <td className="px-2 text-xs text-muted">{f.artifact_type}</td>
                  <td className="px-2 text-xs tabular-nums text-muted">{formatBytes(f.size_bytes)}</td>
                  <td className="px-2 text-xs text-muted">{f.owner_name}</td>
                  <td className="px-2 text-xs text-muted">{timeAgo(f.updated_at)}</td>
                  <td className="px-2"><button className="icon-btn" onClick={() => downloadFile(`/files/${f.id}/download`, f.original_name, 'POST').catch(onError)} aria-label={`Download ${f.original_name}`}><Download size={14} /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  );
}

export function CodeResultsPage() {
  const { data, loading } = useLoad<{ artifacts: { id: string; project_id: string; name: string; artifact_type: string; language: string; linked_code_version: string; metrics: Record<string, number>; updated_at: string; last_editor_name: string; project_title: string }[] }>('/me/artifacts');
  const [type, setType] = useState('');
  const items = (data?.artifacts ?? []).filter((a) => !type || a.artifact_type === type);
  return (
    <PageShell title="Code & Results" hint="Code snapshots and results across projects. Compare code versions in a project's Code tab and results in its Experiments tab. Uploaded code is never executed."
      controls={<select className="input w-auto" value={type} onChange={(e) => setType(e.target.value)} aria-label="Type"><option value="">All</option><option value="code">Code</option><option value="result">Results</option><option value="notebook">Notebooks</option><option value="figure">Figures</option></select>}>
      {loading && !data && <SkeletonRows />}
      {data && items.length === 0 && <div className="card"><EmptyState icon={<Code2 size={26} />} title="Nothing here yet">Add code snapshots from a project's Code tab, or upload code files under Files & data.</EmptyState></div>}
      {items.length > 0 && (
        <div className="card divide-y divide-line">
          {items.map((a) => (
            <a key={a.id} href={href({ name: 'project', projectId: a.project_id, tab: a.artifact_type === 'code' ? 'code' : 'experiments' })} className="flex items-center gap-3 px-3 py-2 hover:bg-raised">
              <Code2 size={15} className="text-muted" />
              <span className="min-w-0 flex-1"><span className="block truncate font-medium">{a.name}</span><span className="block truncate text-xs text-muted">{a.project_title} · {a.artifact_type}{a.language ? ` · ${a.language}` : ''}{a.linked_code_version ? ` · ${a.linked_code_version}` : ''} · {timeAgo(a.updated_at)}</span></span>
              {Object.keys(a.metrics).length > 0 && <span className="hidden text-xs text-muted sm:block">{Object.entries(a.metrics).slice(0, 2).map(([k, v]) => `${k}=${Number(v).toPrecision(3)}`).join(', ')}</span>}
            </a>
          ))}
        </div>
      )}
    </PageShell>
  );
}

export function ReferencesPage() {
  const [q, setQ] = useState('');
  const dq = useDebounced(q);
  const { toast } = useApp();
  const { data, loading } = useLoad<{ references: { id: string; project_id: string; cite_key: string; title: string; authors: string; year: number; doi: string; journal_or_conference: string; project_title: string }[] }>(`/me/references${dq ? `?q=${encodeURIComponent(dq)}` : ''}`);
  return (
    <PageShell title="Literature & References" hint="References from all your project libraries. Import BibTeX, edit entries and export .bib files from a project's References tab."
      controls={<SearchBox value={q} onChange={setQ} placeholder="Title, author, DOI or cite key" />}>
      {loading && !data && <SkeletonRows />}
      {data && data.references.length === 0 && <div className="card"><EmptyState icon={<BookOpen size={26} />} title="No references found" /></div>}
      {data && data.references.length > 0 && (
        <div className="card divide-y divide-line">
          {data.references.map((r) => (
            <div key={r.id} className="flex items-center gap-3 px-3 py-2">
              <a href={href({ name: 'project', projectId: r.project_id, tab: 'references' })} className="min-w-0 flex-1 hover:text-accent">
                <span className="block truncate text-[13px] font-medium">{r.title}</span>
                <span className="block truncate text-xs text-muted">{r.authors} · {r.year}{r.journal_or_conference ? ` · ${r.journal_or_conference}` : ''} · {r.project_title}</span>
              </a>
              <code className="rounded bg-raised px-1.5 py-0.5 text-[11px] text-muted">{r.cite_key}</code>
              <button className="icon-btn" onClick={() => navigator.clipboard.writeText(`\\cite{${r.cite_key}}`).then(() => toast('Copied \\cite command'))} aria-label={`Copy cite command for ${r.cite_key}`}><Copy size={13} /></button>
            </div>
          ))}
        </div>
      )}
    </PageShell>
  );
}

export function ExperimentsPage() {
  const { data, loading } = useLoad<{ experiments: { id: string; project_id: string; name: string; method_or_model: string; dataset_ref: string; dataset_version: string; status: string; created_at: string; project_title: string }[] }>('/me/experiments');
  return (
    <PageShell title="Experiments" hint="Runs across your projects. Log runs and compare their results in a project's Experiments tab.">
      {loading && !data && <SkeletonRows />}
      {data && data.experiments.length === 0 && <div className="card"><EmptyState icon={<FlaskConical size={26} />} title="No experiments yet" /></div>}
      {data && data.experiments.length > 0 && (
        <div className="card divide-y divide-line">
          {data.experiments.map((e) => (
            <a key={e.id} href={href({ name: 'project', projectId: e.project_id, tab: 'experiments' })} className="flex items-center gap-3 px-3 py-2 hover:bg-raised">
              <FlaskConical size={15} className="text-muted" />
              <span className="min-w-0 flex-1"><span className="block truncate font-medium">{e.name}</span><span className="block truncate text-xs text-muted">{e.project_title} · {e.method_or_model} · {e.dataset_ref || 'no dataset'} {e.dataset_version} · {timeAgo(e.created_at)}</span></span>
              <span className="chip">{e.status}</span>
            </a>
          ))}
        </div>
      )}
    </PageShell>
  );
}

export function TasksPage() {
  const [assigned, setAssigned] = useState(false);
  const { data, loading } = useLoad<{ tasks: { id: string; project_id: string; title: string; status: string; priority: string; due_date: string; project_title: string }[] }>(`/me/tasks?assigned=${assigned}`);
  return (
    <PageShell title="Tasks" hint="Tasks across your projects. Create and update tasks in a project's Tasks tab."
      controls={<div className="flex rounded-md border border-line text-xs">
        <button className={`px-3 py-1.5 ${!assigned ? 'bg-raised text-ink' : 'text-muted'}`} onClick={() => setAssigned(false)}>All tasks</button>
        <button className={`px-3 py-1.5 ${assigned ? 'bg-raised text-ink' : 'text-muted'}`} onClick={() => setAssigned(true)}>Assigned to me</button>
      </div>}>
      {loading && !data && <SkeletonRows />}
      {data && data.tasks.length === 0 && <div className="card"><EmptyState icon={<CheckSquare size={26} />} title="No tasks" /></div>}
      {data && data.tasks.length > 0 && (
        <div className="card divide-y divide-line">
          {data.tasks.map((t) => (
            <a key={t.id} href={href({ name: 'project', projectId: t.project_id, tab: 'tasks' })} className={`flex items-center gap-3 px-3 py-2 hover:bg-raised ${t.status === 'done' ? 'opacity-60' : ''}`}>
              <CheckSquare size={15} className="text-muted" />
              <span className="min-w-0 flex-1"><span className="block truncate text-[13px]">{t.title}</span><span className="block truncate text-xs text-muted">{t.project_title}{t.due_date ? ` · due ${t.due_date}` : ''}</span></span>
              <span className={`text-xs ${t.priority === 'urgent' || t.priority === 'high' ? 'text-danger' : 'text-muted'}`}>{t.priority}</span>
              <span className="chip">{t.status.replace('_', ' ')}</span>
            </a>
          ))}
        </div>
      )}
    </PageShell>
  );
}
