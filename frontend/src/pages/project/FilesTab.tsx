import { useEffect, useMemo, useRef, useState, type DragEvent } from 'react';
import { ChevronRight, Database, Download, Eye, FileArchive, FileCode2, FileImage, FileText, Folder, FolderInput, FolderPlus, History, LayoutGrid, List, Pause, Pencil, Play, RotateCcw, Search, Trash2, Upload, X } from 'lucide-react';
import { api, ApiError, downloadFile } from '../../services/apiClient';
import { useApp, useLoad } from '../../lib/app';
import { formatBytes, timeAgo } from '../../lib/text';
import { guessArtifactType, runUpload, type UploadJob } from '../../lib/uploads';
import type { Project } from '../../types';
import { ConfirmDialog, EmptyState, Modal, SkeletonRows, Spinner, useErrorToast } from '../../components/ui';

interface DataFile {
  id: string;
  folder: string;
  original_name: string;
  size_bytes: number;
  media_type: string;
  artifact_type: string;
  description: string;
  tags: string[];
  current_version: number;
  owner_name: string;
  updated_at: string;
  deleted_at: string | null;
  linked_entity_id: string;
  linked_entity_type: string;
}

type SortKey = 'name' | 'type' | 'date' | 'size' | 'owner';

function fileIcon(f: DataFile) {
  if (f.media_type.startsWith('image/')) return <FileImage size={16} />;
  if (['code', 'notebook'].includes(f.artifact_type)) return <FileCode2 size={16} />;
  if (/zip|tar|gzip/.test(f.media_type)) return <FileArchive size={16} />;
  if (f.artifact_type === 'dataset') return <Database size={16} />;
  return <FileText size={16} />;
}

const DATE_WINDOWS: Record<string, number> = { '7d': 7, '30d': 30, '90d': 90 };

function normFolder(raw: string): string {
  const cleaned = '/' + raw.split('/').map((s) => s.trim()).filter(Boolean).join('/');
  return cleaned === '/' ? '/' : cleaned;
}

export function FilesTab({ project }: { project: Project }) {
  const [trash, setTrash] = useState(false);
  const { data, loading, reload } = useLoad<{ files: DataFile[] }>(`/projects/${project.id}/files?trash=${trash}`);
  const [layout, setLayout] = useState<'list' | 'grid'>('list');
  const [folder, setFolder] = useState('/');
  const [extraFolders, setExtraFolders] = useState<string[]>([]);
  const [type, setType] = useState('all');
  const [uploader, setUploader] = useState('all');
  const [since, setSince] = useState('');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<SortKey>('date');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState<DataFile | null>(null);
  const [editing, setEditing] = useState<DataFile | null>(null);
  const [versions, setVersions] = useState<DataFile | null>(null);
  const [toTrash, setToTrash] = useState<DataFile[] | null>(null);
  const [moving, setMoving] = useState(false);
  const [newFolder, setNewFolder] = useState(false);
  const signals = useRef(new Map<string, { cancelled: boolean }>());
  const input = useRef<HTMLInputElement>(null);
  const { toast } = useApp();
  const onError = useErrorToast();
  const canWrite = project.my_role === 'owner' || project.my_role === 'editor';
  const files = useMemo(() => data?.files ?? [], [data]);

  const types = useMemo(() => Array.from(new Set(files.map((f) => f.artifact_type))).sort(), [files]);
  const uploaders = useMemo(() => Array.from(new Set(files.map((f) => f.owner_name))).sort(), [files]);
  const searching = Boolean(q.trim()) || trash;

  // Immediate subfolders of the current folder (folders are paths like "/runs/2026").
  const subfolders = useMemo(() => {
    if (searching) return [];
    const prefix = folder === '/' ? '/' : folder + '/';
    const names = new Set<string>();
    for (const path of [...files.map((f) => f.folder), ...extraFolders]) {
      const p = normFolder(path);
      if (p !== folder && p.startsWith(prefix)) names.add(p.slice(prefix.length).split('/')[0]);
    }
    return Array.from(names).sort();
  }, [files, extraFolders, folder, searching]);

  const shown = useMemo(() => {
    const term = q.trim().toLowerCase();
    const cutoff = since ? Date.now() - DATE_WINDOWS[since] * 86400000 : 0;
    const list = files.filter(
      (f) =>
        (searching || normFolder(f.folder) === folder) &&
        (type === 'all' || f.artifact_type === type) &&
        (uploader === 'all' || f.owner_name === uploader) &&
        (!cutoff || new Date(f.updated_at).getTime() >= cutoff) &&
        (!term || f.original_name.toLowerCase().includes(term) || f.description.toLowerCase().includes(term) || f.tags.some((t) => t.toLowerCase().includes(term))),
    );
    const cmp: Record<SortKey, (a: DataFile, b: DataFile) => number> = {
      name: (a, b) => a.original_name.localeCompare(b.original_name),
      type: (a, b) => a.artifact_type.localeCompare(b.artifact_type),
      date: (a, b) => b.updated_at.localeCompare(a.updated_at),
      size: (a, b) => b.size_bytes - a.size_bytes,
      owner: (a, b) => a.owner_name.localeCompare(b.owner_name),
    };
    return list.sort(cmp[sort]);
  }, [files, folder, type, uploader, since, q, sort, searching]);

  const selectedFiles = shown.filter((f) => selected.has(f.id));
  const toggle = (id: string, on: boolean) => setSelected((s) => {
    const next = new Set(s);
    if (on) next.add(id);
    else next.delete(id);
    return next;
  });
  const openFolder = (path: string) => {
    setFolder(normFolder(path));
    setSelected(new Set());
  };

  const update = (key: string, patch: Partial<UploadJob>) => setJobs((all) => all.map((j) => (j.key === key ? { ...j, ...patch } : j)));

  const start = async (job: UploadJob) => {
    const signal = { cancelled: false };
    signals.current.set(job.key, signal);
    update(job.key, { status: 'uploading', error: undefined });
    try {
      await runUpload(project.id, job, (sent) => update(job.key, { sent }), signal);
      update(job.key, { status: 'done', sent: job.file.size });
      reload();
      window.setTimeout(() => setJobs((all) => all.filter((j) => j.key !== job.key)), 2500);
    } catch (e) {
      if (signal.cancelled) update(job.key, { status: 'paused', uploadId: job.uploadId });
      else update(job.key, { status: 'failed', uploadId: job.uploadId, error: e instanceof Error ? e.message : 'Upload failed' });
    }
  };

  const enqueue = (list: FileList | File[]) => {
    const created: UploadJob[] = Array.from(list).map((file) => ({
      key: `${file.name}-${file.size}-${Math.random()}`,
      file,
      folder,
      artifactType: guessArtifactType(file.name),
      sent: 0,
      status: 'uploading',
    }));
    setJobs((all) => [...all, ...created]);
    created.forEach((j) => start(j));
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (canWrite && !trash && e.dataTransfer.files.length) enqueue(e.dataTransfer.files);
  };

  const bulkDownload = async () => {
    for (const f of selectedFiles) {
      await downloadFile(`/files/${f.id}/download`, f.original_name, 'POST').catch(onError);
    }
  };
  const bulkRestore = async () => {
    await Promise.all(selectedFiles.map((f) => api.post(`/files/${f.id}/restore`))).catch(onError);
    setSelected(new Set());
    reload();
  };

  const crumbs = folder === '/' ? [] : folder.slice(1).split('/');

  return (
    <div onDragOver={(e) => { e.preventDefault(); if (canWrite && !trash) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop} className="relative">
      {dragging && <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-lg border-2 border-dashed border-accent bg-accent/5 text-accent">Drop files to upload to {folder}</div>}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[180px] flex-1">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
          <input className="input pl-8" placeholder="Search all folders by name, description or tag" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search files" />
        </div>
        <select className="input w-auto" value={type} onChange={(e) => setType(e.target.value)} aria-label="Type"><option value="all">All types</option>{types.map((t) => <option key={t}>{t}</option>)}</select>
        <select className="input w-auto" value={uploader} onChange={(e) => setUploader(e.target.value)} aria-label="Uploaded by"><option value="all">Anyone</option>{uploaders.map((u) => <option key={u}>{u}</option>)}</select>
        <select className="input w-auto" value={since} onChange={(e) => setSince(e.target.value)} aria-label="Updated"><option value="">Any date</option><option value="7d">Last 7 days</option><option value="30d">Last 30 days</option><option value="90d">Last 90 days</option></select>
        <select className="input w-auto" value={sort} onChange={(e) => setSort(e.target.value as SortKey)} aria-label="Sort">
          <option value="date">Newest</option><option value="name">Name</option><option value="type">Type</option><option value="size">Size</option><option value="owner">Uploader</option>
        </select>
        <div className="flex rounded-md border border-line">
          <button className={`icon-btn rounded-none ${layout === 'list' ? 'bg-raised text-ink' : ''}`} onClick={() => setLayout('list')} aria-label="List view"><List size={15} /></button>
          <button className={`icon-btn rounded-none ${layout === 'grid' ? 'bg-raised text-ink' : ''}`} onClick={() => setLayout('grid')} aria-label="Grid view"><LayoutGrid size={15} /></button>
        </div>
        <button className="btn-ghost" onClick={() => { setTrash(!trash); setSelected(new Set()); }}>{trash ? 'Back to files' : <><Trash2 size={14} /> Trash</>}</button>
        {canWrite && !trash && (
          <>
            <button className="btn-outline" onClick={() => setNewFolder(true)}><FolderPlus size={14} /> Folder</button>
            <input ref={input} type="file" multiple hidden onChange={(e) => { if (e.target.files) enqueue(e.target.files); e.target.value = ''; }} />
            <button className="btn-primary" onClick={() => input.current?.click()}><Upload size={14} /> Upload</button>
          </>
        )}
      </div>

      <nav aria-label="Folder" className="mb-2 flex flex-wrap items-center gap-1 text-sm">
        {trash ? <span className="font-medium">Trash</span> : searching ? <span className="text-muted">Search results in all folders</span> : (
          <>
            <button className={`rounded px-1.5 py-0.5 ${crumbs.length ? 'text-muted hover:bg-raised hover:text-ink' : 'font-medium'}`} onClick={() => openFolder('/')}>All files</button>
            {crumbs.map((c, i) => (
              <span key={i} className="flex items-center gap-1">
                <ChevronRight size={13} className="text-faint" />
                <button className={`rounded px-1.5 py-0.5 ${i === crumbs.length - 1 ? 'font-medium' : 'text-muted hover:bg-raised hover:text-ink'}`} onClick={() => openFolder('/' + crumbs.slice(0, i + 1).join('/'))}>{c}</button>
              </span>
            ))}
          </>
        )}
      </nav>

      {selectedFiles.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-2 rounded-lg border border-accent/30 bg-accent/5 px-3 py-1.5 text-sm">
          <span className="mr-auto">{selectedFiles.length} selected</span>
          {!trash && <button className="btn-ghost px-2 py-1 text-xs" onClick={bulkDownload}><Download size={13} /> Download</button>}
          {!trash && canWrite && <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setMoving(true)}><FolderInput size={13} /> Move</button>}
          {!trash && canWrite && <button className="btn-ghost px-2 py-1 text-xs text-danger" onClick={() => setToTrash(selectedFiles)}><Trash2 size={13} /> Move to Trash</button>}
          {trash && canWrite && <button className="btn-ghost px-2 py-1 text-xs" onClick={bulkRestore}><RotateCcw size={13} /> Restore</button>}
          <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setSelected(new Set())}>Clear</button>
        </div>
      )}

      {jobs.length > 0 && (
        <div className="card mb-3 divide-y divide-line">
          {jobs.map((j) => (
            <div key={j.key} className="flex items-center gap-3 px-3 py-2 text-sm">
              <span className="min-w-0 flex-1 truncate">{j.file.name} <span className="text-xs text-muted">→ {j.folder}</span></span>
              <div className="h-1.5 w-40 overflow-hidden rounded bg-raised"><div className={`h-full ${j.status === 'failed' ? 'bg-danger' : 'bg-accent'}`} style={{ width: `${(j.sent / Math.max(1, j.file.size)) * 100}%` }} /></div>
              <span className="w-32 truncate text-right text-xs text-muted" title={j.error}>{j.status === 'done' ? 'Uploaded' : j.status === 'failed' ? j.error : j.status === 'paused' ? 'Paused' : `${formatBytes(j.sent)} / ${formatBytes(j.file.size)}`}</span>
              {j.status === 'uploading' && <button className="icon-btn" onClick={() => { const s = signals.current.get(j.key); if (s) s.cancelled = true; }} aria-label="Pause upload"><Pause size={14} /></button>}
              {(j.status === 'failed' || j.status === 'paused') && <button className="icon-btn" onClick={() => start(j)} aria-label="Retry upload"><Play size={14} /></button>}
              {j.status !== 'done' && (
                <button className="icon-btn" aria-label="Cancel upload" onClick={() => {
                  const s = signals.current.get(j.key);
                  if (s) s.cancelled = true;
                  if (j.uploadId) api.del(`/uploads/${j.uploadId}`).catch(() => undefined);
                  setJobs((all) => all.filter((x) => x.key !== j.key));
                }}><X size={14} /></button>
              )}
            </div>
          ))}
        </div>
      )}

      {loading && !data && <SkeletonRows />}
      {data && shown.length === 0 && subfolders.length === 0 && (
        <div className="card"><EmptyState icon={<Database size={26} />} title={trash ? 'Trash is empty' : files.length ? 'Nothing here' : 'No files yet'}>{!trash && canWrite && 'Drag files here or use Upload. Pick several at once; large files are sent in resumable chunks.'}</EmptyState></div>
      )}

      {(shown.length > 0 || subfolders.length > 0) && layout === 'list' && (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted"><tr className="border-b border-line">
              <th className="w-8 px-3"><input type="checkbox" aria-label="Select all" checked={shown.length > 0 && selectedFiles.length === shown.length} onChange={(e) => setSelected(e.target.checked ? new Set(shown.map((f) => f.id)) : new Set())} /></th>
              <th className="py-2 font-medium">Name</th><th className="px-2 font-medium">Type</th><th className="px-2 font-medium">Size</th><th className="px-2 font-medium">Uploaded by</th><th className="px-2 font-medium">Updated</th><th />
            </tr></thead>
            <tbody className="divide-y divide-line">
              {subfolders.map((name) => (
                <tr key={`dir-${name}`} className="cursor-pointer hover:bg-raised/60" onClick={() => openFolder(`${folder === '/' ? '' : folder}/${name}`)}>
                  <td />
                  <td className="py-2"><span className="flex items-center gap-2 font-medium"><Folder size={16} className="text-accent" /> {name}</span></td>
                  <td className="px-2 text-xs text-muted">folder</td><td /><td /><td /><td />
                </tr>
              ))}
              {shown.map((f) => (
                <tr key={f.id} className={`hover:bg-raised/60 ${selected.has(f.id) ? 'bg-accent/5' : ''}`}>
                  <td className="px-3"><input type="checkbox" aria-label={`Select ${f.original_name}`} checked={selected.has(f.id)} onChange={(e) => toggle(f.id, e.target.checked)} /></td>
                  <td className="py-2"><div className="flex items-center gap-2"><span className="text-muted">{fileIcon(f)}</span><span className="min-w-0"><span className="block truncate font-medium">{f.original_name}</span><span className="block truncate text-xs text-muted">{searching ? `${f.folder} · ` : ''}{f.tags.length ? `${f.tags.join(', ')} · ` : ''}{f.current_version > 1 ? `v${f.current_version}` : ''}</span></span></div></td>
                  <td className="px-2 text-xs text-muted">{f.artifact_type}</td>
                  <td className="px-2 text-xs tabular-nums text-muted">{formatBytes(f.size_bytes)}</td>
                  <td className="px-2 text-xs text-muted">{f.owner_name}</td>
                  <td className="px-2 text-xs text-muted">{timeAgo(f.updated_at)}</td>
                  <td className="px-2"><FileActions f={f} trash={trash} canWrite={canWrite} onPreview={setPreview} onEdit={setEditing} onVersions={setVersions} onTrash={(x) => setToTrash([x])} onRestore={() => api.post(`/files/${f.id}/restore`).then(reload).catch(onError)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(shown.length > 0 || subfolders.length > 0) && layout === 'grid' && (
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {subfolders.map((name) => (
            <button key={`dir-${name}`} className="card flex items-center gap-2 p-3 text-left hover:border-accent/50" onClick={() => openFolder(`${folder === '/' ? '' : folder}/${name}`)}>
              <Folder size={18} className="text-accent" /><span className="truncate text-[13px] font-medium">{name}</span>
            </button>
          ))}
          {shown.map((f) => (
            <div key={f.id} className={`card flex flex-col gap-1 p-3 ${selected.has(f.id) ? 'border-accent' : ''}`}>
              <div className="flex items-center gap-2 text-muted">
                <input type="checkbox" aria-label={`Select ${f.original_name}`} checked={selected.has(f.id)} onChange={(e) => toggle(f.id, e.target.checked)} />
                {fileIcon(f)}<span className="truncate text-[13px] font-medium text-ink">{f.original_name}</span>
              </div>
              <span className="text-xs text-muted">{formatBytes(f.size_bytes)} · {f.owner_name}</span>
              <div className="mt-1 flex justify-end"><FileActions f={f} trash={trash} canWrite={canWrite} onPreview={setPreview} onEdit={setEditing} onVersions={setVersions} onTrash={(x) => setToTrash([x])} onRestore={() => api.post(`/files/${f.id}/restore`).then(reload).catch(onError)} /></div>
            </div>
          ))}
        </div>
      )}

      <PreviewModal file={preview} onClose={() => setPreview(null)} />
      <EditFileModal file={editing} onClose={() => setEditing(null)} onSaved={reload} />
      <VersionsModal file={versions} onClose={() => setVersions(null)} />
      <FolderPromptModal
        open={newFolder}
        title="New folder"
        label={`Inside ${folder}`}
        confirmLabel="Create and open"
        onClose={() => setNewFolder(false)}
        onSubmit={(name) => {
          const path = normFolder(`${folder}/${name}`);
          setExtraFolders((f) => [...f, path]);
          openFolder(path);
          toast('Folder created. Upload files into it to keep it.', 'info');
        }}
      />
      <FolderPromptModal
        open={moving}
        title={`Move ${selectedFiles.length} file(s)`}
        label="Destination folder (for example /datasets/raw)"
        confirmLabel="Move"
        initial={folder}
        onClose={() => setMoving(false)}
        onSubmit={async (dest) => {
          const target = normFolder(dest);
          try {
            await Promise.all(selectedFiles.map((f) => api.patch(`/files/${f.id}`, { folder: target })));
            toast(`Moved ${selectedFiles.length} file(s) to ${target}`, 'success');
            setSelected(new Set());
            reload();
          } catch (e) {
            onError(e);
          }
        }}
      />
      <ConfirmDialog
        open={Boolean(toTrash)}
        onClose={() => setToTrash(null)}
        title={toTrash && toTrash.length > 1 ? `Move ${toTrash.length} files to Trash?` : 'Move file to Trash?'}
        danger
        confirmLabel="Move to Trash"
        message={toTrash && toTrash.length === 1
          ? (toTrash[0].linked_entity_id ? `“${toTrash[0].original_name}” is linked to a ${toTrash[0].linked_entity_type || 'record'}. It will be moved to Trash and can be restored.` : `“${toTrash[0].original_name}” will be moved to Trash and can be restored.`)
          : 'They will be moved to Trash and can be restored.'}
        onConfirm={async () => {
          if (!toTrash) return;
          try {
            await Promise.all(toTrash.map((f) => api.del(`/files/${f.id}${f.linked_entity_id ? '?force=true' : ''}`)));
            toast('Moved to Trash', 'success');
            setSelected(new Set());
            reload();
          } catch (e) {
            onError(e);
          }
        }}
      />
    </div>
  );
}

function FolderPromptModal({ open, title, label, confirmLabel, initial = '', onClose, onSubmit }: { open: boolean; title: string; label: string; confirmLabel: string; initial?: string; onClose(): void; onSubmit(value: string): void | Promise<void> }) {
  const [value, setValue] = useState(initial);
  const [openedWith, setOpenedWith] = useState<string | null>(null);
  if (open && openedWith === null) {
    setOpenedWith(initial);
    setValue(initial);
  }
  if (!open && openedWith !== null) setOpenedWith(null);
  const submit = async () => {
    if (!value.trim()) return;
    await onSubmit(value.trim());
    onClose();
  };
  return (
    <Modal open={open} onClose={onClose} title={title} footer={<><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={!value.trim()} onClick={submit}>{confirmLabel}</button></>}>
      <label className="block"><span className="label">{label}</span><input autoFocus className="input font-mono" value={value} onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && submit()} /></label>
    </Modal>
  );
}

function FileActions({ f, trash, canWrite, onPreview, onEdit, onVersions, onTrash, onRestore }: { f: DataFile; trash: boolean; canWrite: boolean; onPreview(f: DataFile): void; onEdit(f: DataFile): void; onVersions(f: DataFile): void; onTrash(f: DataFile): void; onRestore(): void }) {
  const onError = useErrorToast();
  if (trash) return canWrite ? <button className="btn-outline px-2 py-1 text-xs" onClick={onRestore}><RotateCcw size={12} /> Restore</button> : null;
  return (
    <div className="flex justify-end gap-0.5">
      <button className="icon-btn" onClick={() => onPreview(f)} aria-label={`Preview ${f.original_name}`}><Eye size={14} /></button>
      <button className="icon-btn" onClick={() => downloadFile(`/files/${f.id}/download`, f.original_name, 'POST').catch(onError)} aria-label={`Download ${f.original_name}`}><Download size={14} /></button>
      <button className="icon-btn" onClick={() => onVersions(f)} aria-label="Version history"><History size={14} /></button>
      {canWrite && <button className="icon-btn" onClick={() => onEdit(f)} aria-label="Rename or move"><Pencil size={14} /></button>}
      {canWrite && <button className="icon-btn hover:text-danger" onClick={() => onTrash(f)} aria-label="Move to Trash"><Trash2 size={14} /></button>}
    </div>
  );
}

const PREVIEWABLE_TEXT = /^(text\/|application\/(json|x-yaml|toml|sql|x-tex|x-bibtex|x-ipynb\+json))/;

function PreviewModal({ file, onClose }: { file: DataFile | null; onClose(): void }) {
  const [content, setContent] = useState<{ url?: string; text?: string; note?: string } | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!file) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    setLoading(true);
    setContent(null);
    (async () => {
      try {
        if (file.media_type.startsWith('image/') || file.media_type === 'application/pdf') {
          const { blob } = await api.blob(`/files/${file.id}/download`, 'POST');
          objectUrl = URL.createObjectURL(new Blob([blob], { type: file.media_type }));
          if (!cancelled) setContent({ url: objectUrl });
        } else if (PREVIEWABLE_TEXT.test(file.media_type) && file.size_bytes <= 2 * 1024 * 1024) {
          const { blob } = await api.blob(`/files/${file.id}/download`, 'POST');
          const text = await blob.text();
          if (!cancelled) setContent({ text: text.length > 200000 ? text.slice(0, 200000) + '\n… (truncated)' : text });
        } else if (!cancelled) {
          setContent({ note: 'No preview for this file type or size. Download it to open locally. Uploaded code is never executed.' });
        }
      } catch (e) {
        if (!cancelled) setContent({ note: e instanceof ApiError ? e.message : 'Preview failed.' });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [file]);
  return (
    <Modal open={Boolean(file)} onClose={onClose} title={file?.original_name ?? ''} wide>
      {loading && <Spinner />}
      {content?.url && (file?.media_type === 'application/pdf'
        ? <iframe title={file.original_name} src={content.url} className="h-[65vh] w-full rounded border border-line bg-white" />
        : <img src={content.url} alt={file?.original_name} className="mx-auto max-h-[60vh]" />)}
      {content?.text !== undefined && <pre className="max-h-[60vh] overflow-auto rounded bg-raised p-3 font-mono text-xs">{content.text}</pre>}
      {content?.note && <p className="text-sm text-muted">{content.note}</p>}
      {file?.description && <p className="mt-3 text-sm text-muted">{file.description}</p>}
    </Modal>
  );
}

function EditFileModal({ file, onClose, onSaved }: { file: DataFile | null; onClose(): void; onSaved(): void }) {
  const [form, setForm] = useState({ name: '', folder: '', tags: '' });
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const onError = useErrorToast();
  if (file && loadedFor !== file.id) {
    setLoadedFor(file.id);
    setForm({ name: file.original_name, folder: file.folder, tags: file.tags.join(', ') });
  }
  const save = async () => {
    if (!file) return;
    try {
      await api.patch(`/files/${file.id}`, { original_name: form.name, folder: form.folder, tags: form.tags.split(',').map((t) => t.trim()).filter(Boolean) });
      onClose();
      onSaved();
    } catch (e) {
      onError(e);
    }
  };
  return (
    <Modal open={Boolean(file)} onClose={onClose} title="Rename or move" footer={<><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" onClick={save}>Save</button></>}>
      <div className="space-y-3">
        <label className="block"><span className="label">Name</span><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label className="block"><span className="label">Folder</span><input className="input" value={form.folder} onChange={(e) => setForm({ ...form, folder: e.target.value })} /></label>
        <label className="block"><span className="label">Tags (comma separated)</span><input className="input" value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} /></label>
      </div>
    </Modal>
  );
}

function VersionsModal({ file, onClose }: { file: DataFile | null; onClose(): void }) {
  const { data, loading } = useLoad<{ versions: { version_number: number; size_bytes: number; created_at: string; author_name: string; checksum_sha256: string }[] }>(file ? `/files/${file.id}/versions` : null);
  const onError = useErrorToast();
  return (
    <Modal open={Boolean(file)} onClose={onClose} title={`Versions of ${file?.original_name ?? ''}`}>
      {loading && <SkeletonRows rows={2} />}
      <div className="divide-y divide-line">
        {data?.versions.map((v) => (
          <div key={v.version_number} className="flex items-center gap-3 py-2 text-sm">
            <span className="chip">v{v.version_number}</span>
            <span className="min-w-0 flex-1 text-xs text-muted">{v.author_name} · {timeAgo(v.created_at)} · {formatBytes(v.size_bytes)}<br /><code className="text-[10px]">sha256 {v.checksum_sha256.slice(0, 16)}…</code></span>
            <button className="icon-btn" onClick={() => file && downloadFile(`/files/${file.id}/versions/${v.version_number}/content`, file.original_name).catch(onError)} aria-label={`Download version ${v.version_number}`}><Download size={14} /></button>
          </div>
        ))}
      </div>
      <p className="mt-2 flex items-center gap-1 text-xs text-muted"><Folder size={12} /> Uploading a file with the same name into the same folder creates a new version.</p>
    </Modal>
  );
}
