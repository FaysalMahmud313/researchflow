import { useState } from 'react';
import { Check, Crown, MailPlus, UserMinus, X } from 'lucide-react';
import { api, ApiError } from '../../services/apiClient';
import { useApp, useLoad } from '../../lib/app';
import { timeAgo } from '../../lib/text';
import type { Project, ProjectRole } from '../../types';
import { Avatar, ConfirmDialog, Modal, ResearchSignalIcon, RoleBadge, SkeletonRows, Spinner, useErrorToast } from '../../components/ui';

interface Member { user_id: string; role: ProjectRole; joined_at: string; username: string; full_name: string; email: string }
interface PendingInvite { id: string; role: string; invited_username: string; invited_full_name: string; created_at: string }
interface Signal { id: string; user_id: string; username: string; full_name: string; message: string; proposed_contribution: string; status: string; created_at: string }

const RANK: Record<ProjectRole, number> = { viewer: 1, reviewer: 2, editor: 3, owner: 4 };

export function MembersTab({ project, onChanged }: { project: Project; onChanged(): void }) {
  const { user, toast } = useApp();
  const onError = useErrorToast();
  const members = useLoad<{ members: Member[]; pending_invitations: PendingInvite[] }>(`/projects/${project.id}/members`);
  const signals = useLoad<{ signals: Signal[] }>(`/projects/${project.id}/collaboration-signals`);
  const [invite, setInvite] = useState<{ identifier: string; role: ProjectRole } | null>(null);
  const [removing, setRemoving] = useState<Member | null>(null);
  const [transfer, setTransfer] = useState<Member | null>(null);
  const isOwner = project.my_role === 'owner';
  const mySignal = signals.data?.signals.find((s) => s.user_id === user?.id && ['Pending', 'Acknowledged'].includes(s.status));

  const changeRole = async (m: Member, role: string) => {
    try {
      await api.patch(`/projects/${project.id}/members/${m.user_id}`, { role });
      toast(`${m.full_name} is now ${role}`, 'success');
      members.reload();
    } catch (e) {
      onError(e);
    }
  };

  const setSignal = async (s: Signal, status: string) => {
    try {
      await api.patch(`/collaboration-signals/${s.id}`, { status });
      signals.reload();
      if (status === 'Accepted') setInvite({ identifier: s.username, role: 'viewer' });
    } catch (e) {
      onError(e);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
      <section>
        <div className="mb-3 flex items-center gap-2">
          <h2 className="mr-auto font-semibold">Team</h2>
          <button className="btn-primary" onClick={() => setInvite({ identifier: '', role: 'viewer' })}><MailPlus size={14} /> Invite</button>
        </div>
        {members.loading && !members.data && <SkeletonRows />}
        <div className="card divide-y divide-line">
          {members.data?.members.map((m) => (
            <div key={m.user_id} className="flex flex-wrap items-center gap-3 px-3 py-2">
              <Avatar name={m.full_name} userId={m.user_id} size={32} />
              <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium">{m.full_name}{m.user_id === user?.id && <span className="text-muted"> (you)</span>}</span><span className="block truncate text-xs text-muted">@{m.username} · joined {timeAgo(m.joined_at)}</span></span>
              {isOwner && m.role !== 'owner' ? (
                <>
                  <select className="input w-auto py-1 text-xs" value={m.role} onChange={(e) => changeRole(m, e.target.value)} aria-label={`Role of ${m.full_name}`}>
                    <option value="editor">Editor</option><option value="reviewer">Reviewer</option><option value="viewer">Viewer</option>
                  </select>
                  <button className="icon-btn" title="Make owner" onClick={() => setTransfer(m)} aria-label={`Transfer ownership to ${m.full_name}`}><Crown size={14} /></button>
                  <button className="icon-btn hover:text-danger" onClick={() => setRemoving(m)} aria-label={`Remove ${m.full_name}`}><UserMinus size={14} /></button>
                </>
              ) : (
                <RoleBadge role={m.role} />
              )}
            </div>
          ))}
        </div>
        {(members.data?.pending_invitations.length ?? 0) > 0 && (
          <>
            <h3 className="mb-2 mt-4 text-xs font-semibold uppercase text-faint">Pending invitations</h3>
            <div className="card divide-y divide-line">
              {members.data?.pending_invitations.map((i) => (
                <div key={i.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <span className="flex-1">{i.invited_full_name} <span className="text-xs text-muted">@{i.invited_username} · {timeAgo(i.created_at)}</span></span>
                  <RoleBadge role={i.role} />
                  {isOwner && <button className="btn-ghost px-2 py-1 text-xs" onClick={() => api.patch(`/invitations/${i.id}`, { action: 'cancel' }).then(members.reload).catch(onError)}>Cancel</button>}
                </div>
              ))}
            </div>
          </>
        )}
      </section>

      <aside className="card h-fit p-3">
        <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold"><ResearchSignalIcon className="h-4 w-4 text-accent" /> Research signals</h3>
        <p className="mb-3 text-xs text-muted">Collaborators can signal interest in contributing more. A signal never grants access by itself; the owner decides and sends an invitation.</p>
        {!isOwner && (
          mySignal ? (
            <div className="mb-3 flex items-center justify-between rounded-md bg-accent/5 px-2 py-1.5 text-xs"><span>Your signal is {mySignal.status.toLowerCase()}.</span><button className="btn-ghost px-2 py-0.5 text-xs" onClick={() => api.del(`/projects/${project.id}/collaboration-signals/me`).then(signals.reload).catch(onError)}>Withdraw</button></div>
          ) : (
            <button className="btn-outline mb-3 w-full justify-center" onClick={() => api.post(`/projects/${project.id}/collaboration-signals`, { message: '', proposed_contribution: '' }).then(() => { signals.reload(); toast('Signal sent to the owner', 'success'); }).catch(onError)}>
              <ResearchSignalIcon className="h-4 w-4" /> Signal interest in contributing
            </button>
          )
        )}
        <div className="space-y-2">
          {signals.data?.signals.length === 0 && <p className="text-xs text-faint">No active signals.</p>}
          {signals.data?.signals.map((s) => (
            <div key={s.id} className="rounded-md border border-line p-2 text-xs">
              <p className="flex items-center gap-1.5 font-medium text-ink"><Avatar name={s.full_name} userId={s.user_id} size={20} /> {s.full_name} <span className="font-normal text-muted">@{s.username}</span></p>
              {s.message && <p className="mt-0.5 text-muted">{s.message}</p>}
              <p className="mt-0.5 text-faint">{s.status} · {timeAgo(s.created_at)}</p>
              {isOwner && ['Pending', 'Acknowledged'].includes(s.status) && (
                <div className="mt-1.5 flex gap-1">
                  {s.status === 'Pending' && <button className="btn-ghost px-1.5 py-0.5 text-xs" onClick={() => setSignal(s, 'Acknowledged')}>Acknowledge</button>}
                  <button className="btn-ghost px-1.5 py-0.5 text-xs text-success" onClick={() => setSignal(s, 'Accepted')}><Check size={12} /> Accept & invite</button>
                  <button className="btn-ghost px-1.5 py-0.5 text-xs" onClick={() => setSignal(s, 'Declined')}><X size={12} /> Decline</button>
                </div>
              )}
            </div>
          ))}
        </div>
      </aside>

      <InviteModal value={invite} myRole={project.my_role} projectId={project.id} onClose={() => setInvite(null)} onSent={members.reload} />
      <ConfirmDialog open={Boolean(removing)} onClose={() => setRemoving(null)} title="Remove member?" danger confirmLabel="Remove"
        message={`${removing?.full_name} will lose access to this project. Any open editing session is disconnected within about 20 seconds.`}
        onConfirm={async () => { if (removing) { await api.del(`/projects/${project.id}/members/${removing.user_id}`).catch(onError); members.reload(); } }} />
      <ConfirmDialog open={Boolean(transfer)} onClose={() => setTransfer(null)} title="Transfer ownership?" danger confirmLabel="Transfer ownership"
        message={<>{transfer?.full_name} will become the owner, with control over members and publication status. You will become an editor. This cannot be undone by you afterwards.</>}
        onConfirm={async () => { if (transfer) { await api.post(`/projects/${project.id}/transfer-ownership`, { new_owner_user_id: transfer.user_id }).catch(onError); onChanged(); members.reload(); } }} />
    </div>
  );
}

function InviteModal({ value, myRole, projectId, onClose, onSent }: { value: { identifier: string; role: ProjectRole } | null; myRole: ProjectRole; projectId: string; onClose(): void; onSent(): void }) {
  const [identifier, setIdentifier] = useState('');
  const [role, setRole] = useState<ProjectRole>('viewer');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openedFor, setOpenedFor] = useState<object | null>(null);
  const { toast } = useApp();
  if (value && openedFor !== value) {
    setOpenedFor(value);
    setIdentifier(value.identifier);
    setRole(value.role);
    setError(null);
  }
  const allowed = (['editor', 'reviewer', 'viewer'] as ProjectRole[]).filter((r) => RANK[r] <= RANK[myRole]);
  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/projects/${projectId}/invitations`, { identifier: identifier.trim(), role, message });
      toast('Invitation sent', 'success');
      onClose();
      onSent();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not send invitation.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={Boolean(value)} onClose={onClose} title="Invite a collaborator"
      footer={<><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={busy || identifier.trim().length < 3} onClick={send}>{busy && <Spinner size={14} />} Send invitation</button></>}>
      <div className="space-y-3">
        <label className="block"><span className="label">Username or email of a registered researcher</span><input className="input" value={identifier} onChange={(e) => setIdentifier(e.target.value)} /></label>
        <label className="block"><span className="label">Role</span>
          <select className="input" value={role} onChange={(e) => setRole(e.target.value as ProjectRole)}>{allowed.map((r) => <option key={r} value={r}>{r[0].toUpperCase() + r.slice(1)}</option>)}</select>
          <span className="mt-1 block text-[11px] text-faint">You can only assign roles up to your own. Editors write, reviewers comment and suggest, viewers read.</span>
        </label>
        <label className="block"><span className="label">Message (optional)</span><textarea className="input" value={message} onChange={(e) => setMessage(e.target.value)} maxLength={500} /></label>
        {error && <p className="text-sm text-danger">{error}</p>}
      </div>
    </Modal>
  );
}
