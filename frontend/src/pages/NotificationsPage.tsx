import { useState } from 'react';
import { Bell, Check, X } from 'lucide-react';
import { api } from '../services/apiClient';
import { href, navigate, useApp, useLoad } from '../lib/app';
import { timeAgo } from '../lib/text';
import { EmptyState, SkeletonRows, useErrorToast } from '../components/ui';

interface Notification { id: string; kind: string; title: string; message: string; is_read: number; created_at: string; project_id: string | null }
interface Invitation { id: string; project_id: string; project_title: string; role: string; invited_by_name: string; message: string }

export function NotificationsPage() {
  const notes = useLoad<{ notifications: Notification[] }>('/notifications');
  const invites = useLoad<{ invitations: Invitation[] }>('/invitations');
  const [unreadOnly, setUnreadOnly] = useState(false);
  const { toast } = useApp();
  const onError = useErrorToast();
  const items = (notes.data?.notifications ?? []).filter((n) => !unreadOnly || !n.is_read);

  const markRead = (n: Notification) =>
    api.patch(`/notifications/${n.id}`, {}).then(() => notes.setData({ notifications: (notes.data?.notifications ?? []).map((x) => (x.id === n.id ? { ...x, is_read: 1 } : x)) })).catch(onError);

  const respond = async (inv: Invitation, action: 'accept' | 'reject') => {
    try {
      await api.patch(`/invitations/${inv.id}`, { action });
      toast(action === 'accept' ? `Joined ${inv.project_title}` : 'Invitation declined', 'success');
      invites.reload();
      if (action === 'accept') navigate({ name: 'project', projectId: inv.project_id, tab: 'papers' });
    } catch (e) {
      onError(e);
    }
  };

  return (
    <div className="mx-auto h-full max-w-3xl overflow-y-auto px-4 py-6">
      <div className="mb-4 flex items-center gap-2">
        <h1 className="mr-auto text-lg font-semibold">Notifications</h1>
        <label className="flex items-center gap-1.5 text-xs text-muted"><input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} /> Unread only</label>
        <a className="btn-ghost text-xs" href="#/settings">Preferences</a>
      </div>
      {(invites.data?.invitations.length ?? 0) > 0 && (
        <section className="card mb-4 divide-y divide-line">
          {invites.data?.invitations.map((inv) => (
            <div key={inv.id} className="flex flex-wrap items-center gap-2 px-3 py-2.5 text-sm">
              <span className="flex-1"><b>{inv.invited_by_name}</b> invited you to <b>{inv.project_title}</b> as {inv.role}.{inv.message && <span className="block text-xs text-muted">“{inv.message}”</span>}</span>
              <button className="btn-primary px-2 py-1 text-xs" onClick={() => respond(inv, 'accept')}><Check size={12} /> Accept</button>
              <button className="btn-ghost px-2 py-1 text-xs" onClick={() => respond(inv, 'reject')}><X size={12} /> Decline</button>
            </div>
          ))}
        </section>
      )}
      {notes.loading && !notes.data && <SkeletonRows />}
      {notes.data && items.length === 0 && <div className="card"><EmptyState icon={<Bell size={26} />} title={unreadOnly ? 'No unread notifications' : "You're all caught up"} /></div>}
      {items.length > 0 && (
        <ul className="card divide-y divide-line">
          {items.map((n) => (
            <li key={n.id} className={`flex items-start gap-3 px-3 py-2.5 ${n.is_read ? 'opacity-70' : ''}`}>
              {!n.is_read && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-accent" aria-label="Unread" />}
              <span className="min-w-0 flex-1 text-sm">
                <span className="block font-medium">{n.title}</span>
                <span className="block text-muted">{n.message}</span>
                <span className="text-xs text-faint">{timeAgo(n.created_at)}{n.project_id && <> · <a className="hover:text-ink" href={href({ name: 'project', projectId: n.project_id, tab: 'papers' })}>Open project</a></>}</span>
              </span>
              {!n.is_read && <button className="btn-ghost px-2 py-1 text-xs" onClick={() => markRead(n)}>Mark read</button>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
