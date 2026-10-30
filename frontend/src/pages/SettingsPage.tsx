import { useState } from 'react';
import { Check, Monitor, Moon, Sun } from 'lucide-react';
import { api } from '../services/apiClient';
import { ACCENTS, useApp, useLoad } from '../lib/app';
import { timeAgo } from '../lib/text';
import { Spinner, useErrorToast } from '../components/ui';
import { AvatarEditor } from '../components/AvatarEditor';

interface Profile {
  full_name: string;
  username: string;
  email: string;
  profile: { institution: string; department: string; orcid_id: string; bio: string; professional_title: string; notification_preferences?: Record<string, boolean> };
}

export const SHORTCUTS: [string, string][] = [
  ['Ctrl/⌘ + S', 'Save the current file (autosave also saves after a short pause)'],
  ['Ctrl/⌘ + Shift + S', 'Save a named version'],
  ['Ctrl/⌘ + K', 'Command palette: files and actions'],
  ['Ctrl/⌘ + F', 'Find and replace in the current file'],
  ['Ctrl/⌘ + Shift + F', 'Search all files of the paper'],
  ['Ctrl/⌘ + \\', 'Show or hide the tools panel'],
  ['Ctrl/⌘ + Alt + M', 'Comment on the selection'],
  ['Ctrl/⌘ + Z / Shift + Z', 'Undo / redo'],
  ['Alt + click, Alt + drag', 'Add cursor / rectangular selection'],
  ['/', 'Focus global search'],
];

export function SettingsPage() {
  const { theme, setTheme, accent, setAccent, toast, updateUser } = useApp();
  const { data } = useLoad<Profile>('/users/me');
  const [form, setForm] = useState<Record<string, string> | null>(null);
  const [busy, setBusy] = useState(false);
  const onError = useErrorToast();
  if (data && !form) {
    setForm({ full_name: data.full_name, institution: data.profile.institution, department: data.profile.department, orcid_id: data.profile.orcid_id, professional_title: data.profile.professional_title, bio: data.profile.bio });
  }
  const save = async () => {
    if (!form) return;
    setBusy(true);
    try {
      await api.patch('/users/me', form);
      if (form.full_name) updateUser({ full_name: form.full_name.trim() });
      toast('Profile saved', 'success');
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="mx-auto h-full max-w-3xl space-y-6 overflow-y-auto px-4 py-6">
      <section className="card p-4">
        <h2 className="mb-3 font-semibold">Appearance</h2>
        <div className="flex flex-wrap gap-2">
          {([['light', Sun, 'Light'], ['dark', Moon, 'Dark'], ['system', Monitor, 'System']] as const).map(([mode, I, label]) => (
            <button key={mode} onClick={() => setTheme(mode)} className={`btn-outline ${theme === mode ? 'border-accent text-accent' : ''}`}><I size={14} /> {label}</button>
          ))}
        </div>
        <p className="mb-2 mt-4 text-xs text-muted">Accent color</p>
        <div className="flex gap-2">
          {ACCENTS.map((a) => (
            <button key={a.id} onClick={() => setAccent(a.id)} aria-label={a.name} title={a.name} className="flex h-7 w-7 items-center justify-center rounded-full text-white" style={{ background: a.hex }}>
              {accent === a.id && <Check size={14} />}
            </button>
          ))}
        </div>
      </section>
      {form && (
        <section className="card p-4">
          <h2 className="mb-3 font-semibold">Researcher profile</h2>
          <div className="mb-4 border-b border-line pb-4">
            <AvatarEditor />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {([['full_name', 'Full name'], ['professional_title', 'Title'], ['institution', 'Institution'], ['department', 'Department'], ['orcid_id', 'ORCID iD']] as const).map(([k, label]) => (
              <label key={k} className="block"><span className="label">{label}</span><input className="input" value={form[k] ?? ''} onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></label>
            ))}
            <label className="block sm:col-span-2"><span className="label">Bio</span><textarea className="input" value={form.bio ?? ''} onChange={(e) => setForm({ ...form, bio: e.target.value })} /></label>
          </div>
          <div className="mt-3 flex justify-end"><button className="btn-primary" disabled={busy} onClick={save}>{busy && <Spinner size={14} />} Save profile</button></div>
        </section>
      )}
      <PasswordSection />
      <SessionsSection />
      {data && <NotificationSection initial={data.profile.notification_preferences ?? {}} />}
      <section className="card p-4">
        <h2 className="mb-3 font-semibold">Keyboard shortcuts</h2>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          {SHORTCUTS.map(([k, v]) => <div key={k} className="contents"><dt><kbd className="kbd text-[11px]">{k}</kbd></dt><dd className="text-muted">{v}</dd></div>)}
        </dl>
      </section>
    </div>
  );
}

function PasswordSection() {
  const [form, setForm] = useState({ current_password: '', new_password: '', confirm: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useApp();
  const submit = async () => {
    setError(null);
    if (form.new_password !== form.confirm) {
      setError('The new passwords do not match.');
      return;
    }
    setBusy(true);
    try {
      await api.patch('/users/me/password', { current_password: form.current_password, new_password: form.new_password });
      setForm({ current_password: '', new_password: '', confirm: '' });
      toast('Password changed. Other sessions were signed out.', 'success');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change the password.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="card p-4">
      <h2 className="mb-3 font-semibold">Password</h2>
      <div className="grid gap-3 sm:grid-cols-3">
        {([['current_password', 'Current password', 'current-password'], ['new_password', 'New password', 'new-password'], ['confirm', 'Confirm new password', 'new-password']] as const).map(([k, label, ac]) => (
          <label key={k} className="block"><span className="label">{label}</span><input type="password" autoComplete={ac} className="input" value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} /></label>
        ))}
      </div>
      <p className="mt-1 text-[11px] text-faint">At least 10 characters with upper and lower case letters and a digit.</p>
      {error && <p className="mt-2 text-sm text-danger" role="alert">{error}</p>}
      <div className="mt-3 flex justify-end"><button className="btn-primary" disabled={busy || !form.current_password || !form.new_password} onClick={submit}>{busy && <Spinner size={14} />} Change password</button></div>
    </section>
  );
}

function SessionsSection() {
  const { data, reload } = useLoad<{ sessions: { id: string; user_agent: string; ip_address: string; created_at: string; is_current: boolean }[] }>('/users/me/sessions');
  const { toast } = useApp();
  const onError = useErrorToast();
  const others = (data?.sessions ?? []).filter((s) => !s.is_current).length;
  return (
    <section className="card p-4">
      <div className="mb-3 flex items-center">
        <h2 className="mr-auto font-semibold">Signed-in sessions</h2>
        <button className="btn-outline" disabled={!others}
          onClick={() => api.del<{ revoked_count: number }>('/users/me/sessions').then((r) => { toast(`Signed out ${r.revoked_count} other session(s)`, 'success'); reload(); }).catch(onError)}>
          Sign out other sessions
        </button>
      </div>
      <ul className="divide-y divide-line text-sm">
        {data?.sessions.map((s) => (
          <li key={s.id} className="flex items-center gap-2 py-2">
            <span className="min-w-0 flex-1 truncate">{s.user_agent || 'Unknown device'}<span className="block text-xs text-muted">{s.ip_address} · signed in {timeAgo(s.created_at)}</span></span>
            {s.is_current && <span className="chip">This device</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

const NOTIFICATION_OPTIONS: [string, string][] = [
  ['invitations', 'Project invitations'],
  ['mentions', '@mentions in comments'],
  ['comments', 'Replies, review requests and accepted suggestions'],
  ['project_updates', 'Publication status changes and research signals'],
];

function NotificationSection({ initial }: { initial: Record<string, boolean> }) {
  const [prefs, setPrefs] = useState(initial);
  const onError = useErrorToast();
  const toggle = (key: string, value: boolean) => {
    const next = { ...prefs, [key]: value };
    setPrefs(next);
    api.patch('/users/me/preferences', { notification_preferences: next }).catch(onError);
  };
  return (
    <section className="card p-4">
      <h2 className="mb-1 font-semibold">In-app notifications</h2>
      <p className="mb-3 text-xs text-muted">Choose which events create a notification for you.</p>
      <div className="space-y-2">
        {NOTIFICATION_OPTIONS.map(([key, label]) => (
          <label key={key} className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={prefs[key] !== false} onChange={(e) => toggle(key, e.target.checked)} /> {label}
          </label>
        ))}
      </div>
    </section>
  );
}
