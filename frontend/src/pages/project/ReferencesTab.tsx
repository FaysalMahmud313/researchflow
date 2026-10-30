import { useEffect, useState } from 'react';
import { BookOpen, Copy, Download, FileUp, Plus, Search, Trash2, Users2 } from 'lucide-react';
import { api, ApiError, downloadFile } from '../../services/apiClient';
import { useApp, useLoad } from '../../lib/app';
import type { Project, Reference } from '../../types';
import { ConfirmDialog, EmptyState, Modal, SkeletonRows, Spinner, useErrorToast } from '../../components/ui';

export function ReferencesTab({ project }: { project: Project }) {
  const [q, setQ] = useState('');
  const [debounced, setDebounced] = useState('');
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(q.trim()), 200);
    return () => window.clearTimeout(t);
  }, [q]);
  const { data, loading, reload } = useLoad<{ references: Reference[] }>(`/projects/${project.id}/references${debounced ? `?q=${encodeURIComponent(debounced)}` : ''}`);
  const [selected, setSelected] = useState<Reference | null>(null);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [dupes, setDupes] = useState(false);
  const { toast } = useApp();
  const onError = useErrorToast();
  const canWrite = project.my_role === 'owner' || project.my_role === 'editor';
  const refs = data?.references ?? [];

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
      <div className="min-w-0">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <div className="relative min-w-[200px] flex-1">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
            <input className="input pl-8" placeholder="Search title, author, DOI, cite key" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search references" />
          </div>
          <button className="btn-ghost" onClick={() => setDupes(true)}><Users2 size={14} /> Duplicates</button>
          <button className="btn-outline" onClick={() => downloadFile(`/projects/${project.id}/references/library.bib`, 'library.bib').catch(onError)}><Download size={14} /> .bib</button>
          {canWrite && <button className="btn-outline" onClick={() => setImporting(true)}><FileUp size={14} /> Import BibTeX</button>}
          {canWrite && <button className="btn-primary" onClick={() => setAdding(true)}><Plus size={14} /> Add</button>}
        </div>
        {loading && !data && <SkeletonRows />}
        {data && refs.length === 0 && (
          <div className="card"><EmptyState icon={<BookOpen size={26} />} title={debounced ? 'No matching references' : 'Library is empty'}>Import a .bib file or add references manually.</EmptyState></div>
        )}
        {refs.length > 0 && (
          <div className="card divide-y divide-line">
            {refs.map((r) => (
              <button key={r.id} onClick={() => setSelected(r)} className={`flex w-full items-start gap-3 px-3 py-2 text-left hover:bg-raised ${selected?.id === r.id ? 'bg-accent/5' : ''}`}>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium">{r.title}</span>
                  <span className="block truncate text-xs text-muted">{r.authors} · {r.year}{r.journal_or_conference ? ` · ${r.journal_or_conference}` : ''}</span>
                </span>
                <code className="shrink-0 rounded bg-raised px-1.5 py-0.5 text-[11px] text-muted">{r.cite_key}</code>
              </button>
            ))}
          </div>
        )}
      </div>
      <aside className="card h-fit p-3 lg:sticky lg:top-0">
        {selected ? (
          <ReferenceDetail key={selected.id} reference={selected} canWrite={canWrite} onChanged={(r) => { setSelected(r); reload(); }} onDeleted={() => { setSelected(null); reload(); }} />
        ) : (
          <p className="text-sm text-muted">Select a reference to see its metadata, copy its cite key, or edit it.</p>
        )}
      </aside>
      <AddReferenceModal open={adding} onClose={() => setAdding(false)} projectId={project.id} onAdded={() => { reload(); toast('Reference added', 'success'); }} />
      <ImportBibModal open={importing} onClose={() => setImporting(false)} projectId={project.id} onDone={reload} />
      <DuplicatesModal open={dupes} onClose={() => setDupes(false)} projectId={project.id} />
    </div>
  );
}

function ReferenceDetail({ reference, canWrite, onChanged, onDeleted }: { reference: Reference; canWrite: boolean; onChanged(r: Reference): void; onDeleted(): void }) {
  const [key, setKey] = useState(reference.cite_key);
  const [notes, setNotes] = useState(reference.notes);
  const [fields, setFields] = useState(() => Object.entries(reference.fields).map(([k, v]) => ({ k, v })));
  const [entryType, setEntryType] = useState(reference.entry_type);
  const [busy, setBusy] = useState(false);
  const [usages, setUsages] = useState<{ path: string; document_title: string; count: number }[] | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const { toast } = useApp();
  const onError = useErrorToast();

  const save = async (renameInManuscripts = false) => {
    setBusy(true);
    try {
      const res = await api.patch<{ cite_key: string; rewritten_files: string[] }>(`/references/${reference.id}/bibtex`, {
        cite_key: key, entry_type: entryType, fields: Object.fromEntries(fields.filter((f) => f.k.trim()).map((f) => [f.k.trim(), f.v])), rename_in_manuscripts: renameInManuscripts,
      });
      if (notes !== reference.notes) await api.patch(`/references/${reference.id}`, { notes });
      setUsages(null);
      if (res.rewritten_files.length) toast(`Updated citations in ${res.rewritten_files.join(', ')}`, 'success');
      else toast('Reference saved', 'success');
      onChanged({ ...reference, cite_key: res.cite_key, notes, entry_type: entryType, fields: Object.fromEntries(fields.map((f) => [f.k, f.v])) });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail && typeof e.detail === 'object' && 'usages' in e.detail) {
        setUsages((e.detail as { usages: { path: string; document_title: string; count: number }[] }).usages);
      } else onError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3 text-sm">
      <div>
        <p className="font-medium leading-snug">{reference.title}</p>
        <p className="text-xs text-muted">{reference.authors} ({reference.year})</p>
        {reference.doi && <a className="text-xs text-accent hover:underline" href={`https://doi.org/${reference.doi}`} target="_blank" rel="noopener noreferrer">doi:{reference.doi}</a>}
      </div>
      <div className="flex items-center gap-2">
        <input className="input font-mono text-xs" value={key} onChange={(e) => setKey(e.target.value)} disabled={!canWrite} aria-label="Cite key" />
        <button className="icon-btn" onClick={() => navigator.clipboard.writeText(`\\cite{${reference.cite_key}}`).then(() => toast('Copied \\cite command'))} title="Copy \cite{…}" aria-label="Copy cite command"><Copy size={14} /></button>
      </div>
      {usages && (
        <div className="rounded-md border border-warn/40 bg-warn/10 p-2 text-xs">
          <p className="font-medium">“{reference.cite_key}” is cited in:</p>
          <ul className="my-1 list-disc pl-4">{usages.map((u) => <li key={u.path + u.document_title}>{u.document_title} · {u.path} ({u.count}×)</li>)}</ul>
          <p>Rename the key and update these citations?</p>
          <div className="mt-1.5 flex gap-2"><button className="btn-primary px-2 py-1 text-xs" onClick={() => save(true)}>Rename & update citations</button><button className="btn-ghost px-2 py-1 text-xs" onClick={() => { setUsages(null); setKey(reference.cite_key); }}>Cancel</button></div>
        </div>
      )}
      <label className="block"><span className="label">Entry type</span><input className="input text-xs" value={entryType} onChange={(e) => setEntryType(e.target.value)} disabled={!canWrite} /></label>
      <div>
        <span className="label">BibTeX fields (custom fields are kept)</span>
        <div className="space-y-1">
          {fields.map((f, i) => (
            <div key={i} className="flex gap-1">
              <input className="input w-28 font-mono text-[11px]" value={f.k} disabled={!canWrite} onChange={(e) => setFields((all) => all.map((x, j) => (j === i ? { ...x, k: e.target.value } : x)))} aria-label="Field name" />
              <input className="input text-[12px]" value={f.v} disabled={!canWrite} onChange={(e) => setFields((all) => all.map((x, j) => (j === i ? { ...x, v: e.target.value } : x)))} aria-label={`${f.k} value`} />
            </div>
          ))}
          {canWrite && <button className="btn-ghost px-1 py-0.5 text-xs" onClick={() => setFields((all) => [...all, { k: '', v: '' }])}><Plus size={12} /> Field</button>}
        </div>
      </div>
      <label className="block"><span className="label">Notes</span><textarea className="input min-h-[60px] text-xs" value={notes} onChange={(e) => setNotes(e.target.value)} disabled={!canWrite} /></label>
      {canWrite && (
        <div className="flex justify-between">
          <button className="btn-ghost text-danger" onClick={() => setConfirmDelete(true)}><Trash2 size={14} /> Delete</button>
          <button className="btn-primary" disabled={busy} onClick={() => save(false)}>{busy && <Spinner size={14} />} Save</button>
        </div>
      )}
      <ConfirmDialog open={confirmDelete} onClose={() => setConfirmDelete(false)} title="Delete reference?" danger confirmLabel="Delete"
        message="Papers that cite this key keep their \cite commands; the key will show as undefined until a .bib file defines it."
        onConfirm={async () => { await api.del(`/references/${reference.id}`).catch(onError); onDeleted(); }} />
    </div>
  );
}

function AddReferenceModal({ open, onClose, projectId, onAdded }: { open: boolean; onClose(): void; projectId: string; onAdded(): void }) {
  const empty = { title: '', authors: '', year: String(new Date().getFullYear()), doi: '', journal_or_conference: '', abstract: '' };
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState(false);
  const [lookupMsg, setLookupMsg] = useState<string | null>(null);
  const onError = useErrorToast();
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const lookup = async () => {
    setLookupMsg(null);
    try {
      const res = await api.post<{ fields: Record<string, string> }>('/references/lookup-doi', { doi: form.doi });
      setForm((f) => ({
        ...f,
        title: res.fields.title || f.title,
        authors: res.fields.author || f.authors,
        year: res.fields.year || f.year,
        journal_or_conference: res.fields.journal || res.fields.booktitle || f.journal_or_conference,
      }));
      setLookupMsg('Filled from the DOI record. Check the details before saving.');
    } catch (e) {
      setLookupMsg(e instanceof Error ? e.message : 'Lookup failed. Enter the details manually.');
    }
  };

  const save = async () => {
    setBusy(true);
    try {
      await api.post(`/projects/${projectId}/references`, { ...form, year: Number(form.year) });
      setForm(empty);
      onClose();
      onAdded();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onClose={onClose} title="Add reference"
      footer={<><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={busy || !form.title || !form.authors} onClick={save}>{busy && <Spinner size={14} />} Add</button></>}>
      <div className="space-y-3">
        <div className="flex items-end gap-2">
          <label className="block flex-1"><span className="label">DOI</span><input className="input" value={form.doi} onChange={set('doi')} placeholder="10.xxxx/…" /></label>
          <button className="btn-outline" disabled={form.doi.length < 6} onClick={lookup}>Look up</button>
        </div>
        {lookupMsg && <p className="text-xs text-muted">{lookupMsg}</p>}
        <label className="block"><span className="label">Title</span><input className="input" value={form.title} onChange={set('title')} /></label>
        <label className="block"><span className="label">Authors (Last, First and Last, First)</span><input className="input" value={form.authors} onChange={set('authors')} /></label>
        <div className="grid grid-cols-3 gap-2">
          <label className="block"><span className="label">Year</span><input className="input" type="number" value={form.year} onChange={set('year')} /></label>
          <label className="col-span-2 block"><span className="label">Journal / venue</span><input className="input" value={form.journal_or_conference} onChange={set('journal_or_conference')} /></label>
        </div>
      </div>
    </Modal>
  );
}

function ImportBibModal({ open, onClose, projectId, onDone }: { open: boolean; onClose(): void; projectId: string; onDone(): void }) {
  const [text, setText] = useState('');
  const [skip, setSkip] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ created: { cite_key: string }[]; duplicates: { key: string; matches: { reason: string; cite_key: string } }[]; errors: { line: number; message: string }[] } | null>(null);
  const onError = useErrorToast();
  const run = async () => {
    setBusy(true);
    try {
      const res = await api.post<NonNullable<typeof result>>(`/projects/${projectId}/references/import-bibtex`, { bibtex: text, skip_duplicates: skip });
      setResult(res);
      onDone();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal wide open={open} onClose={() => { setResult(null); setText(''); onClose(); }} title="Import BibTeX"
      footer={result ? <button className="btn-primary" onClick={() => { setResult(null); setText(''); onClose(); }}>Done</button> : <><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={busy || !text.trim()} onClick={run}>{busy && <Spinner size={14} />} Import</button></>}>
      {!result ? (
        <div className="space-y-2">
          <input type="file" accept=".bib,text/plain" className="text-xs" onChange={async (e) => e.target.files?.[0] && setText(await e.target.files[0].text())} />
          <textarea className="input min-h-[240px] font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)} placeholder="@article{key, …}" />
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={skip} onChange={(e) => setSkip(e.target.checked)} /> Skip likely duplicates (same key, DOI or title)</label>
        </div>
      ) : (
        <div className="space-y-2 text-sm">
          <p><b>{result.created.length}</b> imported, <b>{result.duplicates.length}</b> skipped as duplicates, <b>{result.errors.length}</b> could not be parsed.</p>
          {result.duplicates.length > 0 && <ul className="list-disc pl-5 text-xs text-muted">{result.duplicates.map((d) => <li key={d.key}>{d.key}: {d.matches.reason} as {d.matches.cite_key}</li>)}</ul>}
          {result.errors.length > 0 && <ul className="list-disc pl-5 text-xs text-danger">{result.errors.map((er, i) => <li key={i}>Line {er.line}: {er.message}</li>)}</ul>}
        </div>
      )}
    </Modal>
  );
}

function DuplicatesModal({ open, onClose, projectId }: { open: boolean; onClose(): void; projectId: string }) {
  const { data, loading } = useLoad<{ groups: { reason: string; references: Reference[] }[] }>(open ? `/projects/${projectId}/references/duplicates` : null);
  return (
    <Modal open={open} onClose={onClose} title="Likely duplicates" wide>
      {loading && <SkeletonRows rows={3} />}
      {data && data.groups.length === 0 && <p className="text-sm text-muted">No likely duplicates found.</p>}
      {data?.groups.map((g, i) => (
        <div key={i} className="mb-3 rounded-md border border-line p-2">
          <p className="mb-1 text-xs font-medium uppercase text-faint">Same {g.reason}</p>
          {g.references.map((r) => <p key={r.id} className="text-sm"><code className="text-xs">{r.cite_key}</code> — {r.title} ({r.year})</p>)}
        </div>
      ))}
    </Modal>
  );
}
