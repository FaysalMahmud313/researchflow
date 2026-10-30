import { useState } from 'react';
import { Activity, BookOpen, CheckSquare, Code2, Database, FileText, FlaskConical, Lock, Users } from 'lucide-react';
import { api, ApiError } from '../services/apiClient';
import { href, useApp, useLoad } from '../lib/app';
import { PUBLICATION_STATUSES, type Project } from '../types';
import { ResearchSignalIcon, RoleBadge, SkeletonRows, Spinner, StatusBadge, useErrorToast } from '../components/ui';
import { PapersTab } from './project/PapersTab';
import { ReferencesTab } from './project/ReferencesTab';
import { FilesTab } from './project/FilesTab';
import { ExperimentsTab } from './project/ExperimentsTab';
import { CodeTab } from './project/CodeTab';
import { TasksTab } from './project/TasksTab';
import { MembersTab } from './project/MembersTab';
import { ActivityTab } from './project/ActivityTab';

const TABS = [
  { id: 'papers', label: 'Papers', icon: FileText },
  { id: 'references', label: 'References', icon: BookOpen },
  { id: 'files', label: 'Files & data', icon: Database },
  { id: 'experiments', label: 'Experiments', icon: FlaskConical },
  { id: 'code', label: 'Code', icon: Code2 },
  { id: 'tasks', label: 'Tasks', icon: CheckSquare },
  { id: 'members', label: 'Team', icon: Users },
  { id: 'activity', label: 'Activity', icon: Activity },
];

export function ProjectPage({ projectId, tab }: { projectId: string; tab: string }) {
  const { data: project, error, loading, reload, setData } = useLoad<Project>(`/projects/${projectId}`);
  const { toast } = useApp();
  const onError = useErrorToast();
  const [savingStatus, setSavingStatus] = useState(false);

  if (loading && !project) return <div className="mx-auto max-w-6xl p-6"><SkeletonRows rows={6} /></div>;
  if (error || !project) return <NoAccess projectId={projectId} message={error} />;

  const isOwner = project.my_role === 'owner';
  const setStatus = async (publication_status: string) => {
    setSavingStatus(true);
    try {
      await api.patch(`/projects/${projectId}/publication-status`, { publication_status });
      setData({ ...project, publication_status });
      toast('Publication status updated', 'success');
    } catch (e) {
      onError(e);
    } finally {
      setSavingStatus(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-3 gap-y-1 px-4 pt-4">
          <a href="#/mine" className="text-xs text-muted hover:text-ink">Projects</a>
          <span className="text-xs text-faint">/</span>
          <h1 className="min-w-0 truncate text-lg font-semibold">{project.title}</h1>
          <RoleBadge role={project.my_role} />
          <div className="ml-auto flex items-center gap-2">
            {isOwner ? (
              <label className="flex items-center gap-1.5 text-xs text-muted">
                Publication status
                <select className="input w-auto py-1" value={project.publication_status} disabled={savingStatus} onChange={(e) => setStatus(e.target.value)}>
                  {PUBLICATION_STATUSES.map((s) => <option key={s}>{s}</option>)}
                </select>
              </label>
            ) : (
              <span title="Only the project owner can change the publication status"><StatusBadge status={project.publication_status} /></span>
            )}
          </div>
        </div>
        <nav className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-2" aria-label="Project sections">
          {TABS.map((t) => (
            <a key={t.id} href={href({ name: 'project', projectId, tab: t.id })} className={`tab inline-flex items-center gap-1.5 ${tab === t.id ? 'tab-active' : ''}`} aria-current={tab === t.id ? 'page' : undefined}>
              <t.icon size={14} /> {t.label}
            </a>
          ))}
        </nav>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl px-4 py-4">
          {tab === 'papers' && <PapersTab project={project} />}
          {tab === 'references' && <ReferencesTab project={project} />}
          {tab === 'files' && <FilesTab project={project} />}
          {tab === 'experiments' && <ExperimentsTab project={project} />}
          {tab === 'code' && <CodeTab project={project} />}
          {tab === 'tasks' && <TasksTab project={project} />}
          {tab === 'members' && <MembersTab project={project} onChanged={reload} />}
          {tab === 'activity' && <ActivityTab project={project} />}
        </div>
      </div>
    </div>
  );
}

function NoAccess({ projectId, message }: { projectId: string; message: string | null }) {
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [note, setNote] = useState('');
  const { toast } = useApp();
  const raise = async () => {
    setBusy(true);
    try {
      await api.post(`/projects/${projectId}/collaboration-signals`, { message: note, proposed_contribution: '' });
      setSent(true);
      toast('Signal sent to the project owner. Access is only granted by invitation.', 'success');
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setSent(true);
      else toast(e instanceof Error ? e.message : 'Could not send the signal.', 'error');
    } finally {
      setBusy(false);
    }
  };
  const withdraw = async () => {
    await api.del(`/projects/${projectId}/collaboration-signals/me`).catch(() => undefined);
    setSent(false);
  };
  return (
    <div className="mx-auto max-w-md p-8 text-center">
      <Lock className="mx-auto mb-2 text-faint" size={28} />
      <h1 className="font-semibold">You don't have access to this project</h1>
      <p className="mt-1 text-sm text-muted">{message}</p>
      <div className="card mt-5 space-y-2 p-4 text-left">
        <p className="flex items-center gap-2 text-sm font-medium"><ResearchSignalIcon className="h-4 w-4 text-accent" /> Signal interest</p>
        <p className="text-xs text-muted">Let the owner know you'd like to contribute. This does not grant access; the owner decides whether to invite you.</p>
        {!sent ? (
          <>
            <textarea className="input" placeholder="How would you like to contribute? (optional)" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
            <button className="btn-primary" disabled={busy} onClick={raise}>{busy ? <Spinner size={14} /> : <ResearchSignalIcon className="h-4 w-4" />} Send signal</button>
          </>
        ) : (
          <div className="flex items-center justify-between text-sm"><span className="text-success">Signal sent.</span><button className="btn-ghost" onClick={withdraw}>Withdraw</button></div>
        )}
      </div>
    </div>
  );
}
