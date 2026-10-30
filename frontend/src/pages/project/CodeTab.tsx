import { useEffect, useState } from 'react';
import { Code2, Columns2, Plus, Rows2 } from 'lucide-react';
import { api } from '../../services/apiClient';
import { useApp, useLoad } from '../../lib/app';
import { timeAgo } from '../../lib/text';
import type { Project } from '../../types';
import { DiffView } from '../../components/DiffView';
import { EmptyState, Modal, SkeletonRows, Spinner, useErrorToast } from '../../components/ui';

interface Artifact {
  id: string;
  name: string;
  artifact_type: string;
  language: string;
  content_text: string;
  linked_code_version: string;
  linked_experiment_id: string;
  last_editor_name: string;
  created_at: string;
  notes: string;
}

interface CodeFile { id: string; original_name: string; artifact_type: string; current_version: number; media_type: string }

type Side = { kind: 'artifact'; id: string } | { kind: 'file'; id: string; version: number } | null;

export function CodeTab({ project }: { project: Project }) {
  const arts = useLoad<{ artifacts: Artifact[] }>(`/projects/${project.id}/artifacts?artifact_type=code`);
  const files = useLoad<{ files: CodeFile[] }>(`/projects/${project.id}/files`);
  const [left, setLeft] = useState<Side>(null);
  const [right, setRight] = useState<Side>(null);
  const [mode, setMode] = useState<'split' | 'unified'>(() => (window.innerWidth < 900 ? 'unified' : 'split'));
  const [texts, setTexts] = useState<{ left: string; right: string; leftTitle: string; rightTitle: string; lang: string } | null>(null);
  const [adding, setAdding] = useState(false);
  const [loading, setLoading] = useState(false);
  const onError = useErrorToast();
  const canWrite = project.my_role === 'owner' || project.my_role === 'editor';

  const codeFiles = (files.data?.files ?? []).filter((f) => ['code', 'notebook'].includes(f.artifact_type) || /^text\//.test(f.media_type));
  const artifacts = arts.data?.artifacts ?? [];

  const options: { value: string; label: string; side: Side }[] = [
    ...artifacts.map((a) => ({ value: `a:${a.id}`, label: `${a.name}${a.linked_code_version ? ` (${a.linked_code_version})` : ''}`, side: { kind: 'artifact', id: a.id } as Side })),
    ...codeFiles.flatMap((f) => Array.from({ length: f.current_version }, (_, i) => ({
      value: `f:${f.id}:${f.current_version - i}`,
      label: `${f.original_name} · v${f.current_version - i}`,
      side: { kind: 'file', id: f.id, version: f.current_version - i } as Side,
    }))),
  ];

  useEffect(() => {
    if (!left || !right) return;
    let cancelled = false;
    const load = async (s: NonNullable<Side>): Promise<{ text: string; title: string; lang: string }> => {
      if (s.kind === 'artifact') {
        const a = artifacts.find((x) => x.id === s.id)!;
        return { text: a.content_text, title: `${a.name} ${a.linked_code_version} · ${a.last_editor_name}`, lang: a.language };
      }
      const f = codeFiles.find((x) => x.id === s.id)!;
      const { blob } = await api.blob(`/files/${s.id}/versions/${s.version}/content`);
      if (blob.size > 3 * 1024 * 1024) throw new Error('This version is too large to compare in the browser.');
      return { text: await blob.text(), title: `${f.original_name} v${s.version}`, lang: f.original_name };
    };
    setLoading(true);
    Promise.all([load(left), load(right)])
      .then(([l, r]) => !cancelled && setTexts({ left: l.text, right: r.text, leftTitle: l.title, rightTitle: r.title, lang: r.lang || l.lang }))
      .catch((e) => !cancelled && onError(e))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [left, right]);

  const pick = (v: string) => options.find((o) => o.value === v)?.side ?? null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto font-semibold">Code comparison</h2>
        {canWrite && <button className="btn-outline" onClick={() => setAdding(true)}><Plus size={14} /> Add code snapshot</button>}
      </div>
      {(arts.loading || files.loading) && !arts.data && <SkeletonRows rows={2} />}
      {arts.data && options.length < 2 && (
        <div className="card"><EmptyState icon={<Code2 size={26} />} title="Nothing to compare yet">Add code snapshots here, or upload source files under Files & data. Re-uploading a file creates versions you can compare. Uploaded code is never executed.</EmptyState></div>
      )}
      {options.length >= 2 && (
        <div className="card space-y-3 p-3">
          <div className="flex flex-wrap items-end gap-2">
            <label className="min-w-[200px] flex-1"><span className="label">Original</span>
              <select className="input" onChange={(e) => setLeft(pick(e.target.value))} defaultValue=""><option value="" disabled>Choose…</option>{options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
            </label>
            <label className="min-w-[200px] flex-1"><span className="label">Changed</span>
              <select className="input" onChange={(e) => setRight(pick(e.target.value))} defaultValue=""><option value="" disabled>Choose…</option>{options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
            </label>
            <div className="flex rounded-md border border-line">
              <button className={`btn-ghost rounded-none ${mode === 'split' ? 'bg-raised text-ink' : ''}`} onClick={() => setMode('split')}><Columns2 size={14} /> Side by side</button>
              <button className={`btn-ghost rounded-none ${mode === 'unified' ? 'bg-raised text-ink' : ''}`} onClick={() => setMode('unified')}><Rows2 size={14} /> Unified</button>
            </div>
          </div>
          {loading && <Spinner />}
          {texts && !loading && (
            <>
              <div className="grid grid-cols-2 gap-2 text-xs text-muted"><span>− {texts.leftTitle}</span><span>+ {texts.rightTitle}</span></div>
              <DiffView left={texts.left} right={texts.right} language={texts.lang} mode={mode} />
            </>
          )}
        </div>
      )}
      {artifacts.length > 0 && (
        <div className="card divide-y divide-line">
          {artifacts.map((a) => (
            <div key={a.id} className="flex items-center gap-3 px-3 py-2 text-sm">
              <Code2 size={15} className="text-muted" />
              <span className="min-w-0 flex-1"><span className="block truncate font-medium">{a.name}</span><span className="block text-xs text-muted">{a.language} · {a.linked_code_version || 'unversioned'} · {a.last_editor_name} · {timeAgo(a.created_at)}</span></span>
            </div>
          ))}
        </div>
      )}
      <AddSnapshotModal open={adding} onClose={() => setAdding(false)} projectId={project.id} onAdded={arts.reload} />
    </div>
  );
}

function AddSnapshotModal({ open, onClose, projectId, onAdded }: { open: boolean; onClose(): void; projectId: string; onAdded(): void }) {
  const [form, setForm] = useState({ name: '', language: 'python', linked_code_version: 'v1', content_text: '', notes: '' });
  const [busy, setBusy] = useState(false);
  const { toast } = useApp();
  const onError = useErrorToast();
  const save = async () => {
    setBusy(true);
    try {
      await api.post(`/projects/${projectId}/artifacts`, { ...form, artifact_type: 'code' });
      toast('Snapshot saved', 'success');
      onClose();
      onAdded();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal wide open={open} onClose={onClose} title="Add code snapshot" footer={<><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={busy || !form.name || !form.content_text} onClick={save}>{busy && <Spinner size={14} />} Save</button></>}>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block"><span className="label">Name</span><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label className="block"><span className="label">Language</span><input className="input" value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })} /></label>
        <label className="block"><span className="label">Version label</span><input className="input" value={form.linked_code_version} onChange={(e) => setForm({ ...form, linked_code_version: e.target.value })} /></label>
        <label className="block sm:col-span-3"><span className="label">Code (paste, or load a file)</span>
          <input type="file" className="mb-1 text-xs" onChange={async (e) => { const f = e.target.files?.[0]; if (f) setForm((s) => ({ ...s, content_text: '', name: s.name || f.name })); if (f) { const t = await f.text(); setForm((s) => ({ ...s, content_text: t })); } }} />
          <textarea className="input min-h-[220px] font-mono text-xs" value={form.content_text} onChange={(e) => setForm({ ...form, content_text: e.target.value })} spellCheck={false} />
        </label>
      </div>
    </Modal>
  );
}
