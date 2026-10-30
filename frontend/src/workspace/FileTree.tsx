import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronDown, ChevronRight, File, FileCode2, FileImage, FilePlus2, Folder, FolderOpen, FolderPlus, MoreHorizontal, Pencil, RotateCcw, Star, Trash2, Upload, BookMarked,
} from 'lucide-react';
import { api } from '../services/apiClient';
import { useApp } from '../lib/app';
import { timeAgo } from '../lib/text';
import type { Manuscript, ManuscriptFile } from '../types';
import { ConfirmDialog, Dropdown, Modal, useErrorToast } from '../components/ui';

interface Node {
  name: string;
  path: string;
  file?: ManuscriptFile;
  children: Node[];
}

function buildTree(files: ManuscriptFile[]): Node {
  const root: Node = { name: '', path: '', children: [] };
  const byPath = new Map<string, Node>([['', root]]);
  const ensure = (path: string): Node => {
    const existing = byPath.get(path);
    if (existing) return existing;
    const parentPath = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '';
    const node: Node = { name: path.split('/').pop() || path, path, children: [] };
    ensure(parentPath).children.push(node);
    byPath.set(path, node);
    return node;
  };
  for (const f of files) {
    const node = ensure(f.path);
    node.file = f;
  }
  const sort = (n: Node) => {
    n.children.sort((a, b) => {
      const af = !a.file || a.file.file_kind === 'folder';
      const bf = !b.file || b.file.file_kind === 'folder';
      return af === bf ? a.name.localeCompare(b.name) : af ? -1 : 1;
    });
    n.children.forEach(sort);
  };
  sort(root);
  return root;
}

function iconFor(f?: ManuscriptFile) {
  if (!f) return <File size={14} />;
  if (f.file_kind === 'binary') return <FileImage size={14} />;
  if (f.path.endsWith('.bib')) return <BookMarked size={14} />;
  if (f.path.endsWith('.tex')) return <FileCode2 size={14} />;
  return <File size={14} />;
}

interface Props {
  manuscript: Manuscript;
  files: ManuscriptFile[];
  activeFileId: string | null;
  canWrite: boolean;
  onOpen(file: ManuscriptFile): void;
  onChanged(): void;
}

export function FileTree({ manuscript, files, activeFileId, canWrite, onOpen, onChanged }: Props) {
  const tree = useMemo(() => buildTree(files), [files]);
  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem(`rf_tree_${manuscript.id}`) || '[]'));
    } catch {
      return new Set();
    }
  });
  const [creating, setCreating] = useState<{ kind: 'text' | 'folder'; folder: string } | null>(null);
  const [renaming, setRenaming] = useState<ManuscriptFile | null>(null);
  const [deleting, setDeleting] = useState<ManuscriptFile | null>(null);
  const [trashOpen, setTrashOpen] = useState(false);
  const [uploadFolder, setUploadFolder] = useState('');
  const upload = useRef<HTMLInputElement>(null);
  const { toast } = useApp();
  const onError = useErrorToast();

  const toggle = (path: string) => {
    const next = new Set(collapsed);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    setCollapsed(next);
    try {
      localStorage.setItem(`rf_tree_${manuscript.id}`, JSON.stringify(Array.from(next)));
    } catch {
      /* ignore */
    }
  };

  const doUpload = async (list: FileList, folder: string) => {
    const form = new FormData();
    Array.from(list).forEach((f) => form.append('files', f));
    form.append('folder', folder);
    try {
      const res = await api.form<{ files: { path: string }[] }>(`/manuscripts/${manuscript.id}/files/upload`, form);
      toast(`Uploaded ${res.files.map((f) => f.path).join(', ')}`, 'success');
      onChanged();
    } catch (e) {
      onError(e);
    }
  };

  const renderNode = (node: Node, depth: number): JSX.Element[] => {
    const isFolder = !node.file || node.file.file_kind === 'folder';
    const open = !collapsed.has(node.path);
    const isMain = node.file?.path === manuscript.main_file_path;
    const row = (
      <div
        key={node.path}
        className={`group flex items-center gap-1 rounded-md pr-1 text-[13px] ${node.file?.id === activeFileId ? 'bg-accent/10 text-ink' : 'text-muted hover:bg-raised hover:text-ink'}`}
        style={{ paddingLeft: 4 + depth * 12 }}
      >
        <button
          className="flex min-w-0 flex-1 items-center gap-1.5 py-1 text-left"
          onClick={() => (isFolder ? toggle(node.path) : node.file && onOpen(node.file))}
          aria-expanded={isFolder ? open : undefined}
          title={node.file ? `${node.path} · ${timeAgo(node.file.updated_at)}` : node.path}
        >
          {isFolder ? (open ? <ChevronDown size={12} /> : <ChevronRight size={12} />) : <span className="w-3" />}
          {isFolder ? (open ? <FolderOpen size={14} /> : <Folder size={14} />) : iconFor(node.file)}
          <span className="truncate">{node.name}</span>
          {isMain && <Star size={11} className="shrink-0 fill-current text-warn" aria-label="Main file" />}
        </button>
        {canWrite && node.file && <NodeMenu node={node} isFolder={isFolder} isMain={isMain} onNewFile={() => setCreating({ kind: 'text', folder: node.path })} onNewFolder={() => setCreating({ kind: 'folder', folder: node.path })}
          onUpload={() => { setUploadFolder(node.path); upload.current?.click(); }} onRename={() => setRenaming(node.file!)} onDelete={() => setDeleting(node.file!)}
          onMain={() => api.patch(`/manuscripts/${manuscript.id}`, { main_file_path: node.path }).then(onChanged).catch(onError)} />}
      </div>
    );
    if (!isFolder || !open) return [row];
    return [row, ...node.children.flatMap((c) => renderNode(c, depth + 1))];
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-0.5 border-b border-line px-2 py-1">
        <span className="mr-auto text-[11px] font-semibold uppercase tracking-wide text-faint">Files</span>
        {canWrite && (
          <>
            <button className="icon-btn" onClick={() => setCreating({ kind: 'text', folder: '' })} aria-label="New file" title="New file"><FilePlus2 size={14} /></button>
            <button className="icon-btn" onClick={() => setCreating({ kind: 'folder', folder: '' })} aria-label="New folder" title="New folder"><FolderPlus size={14} /></button>
            <button className="icon-btn" onClick={() => { setUploadFolder(''); upload.current?.click(); }} aria-label="Upload files" title="Upload files"><Upload size={14} /></button>
          </>
        )}
        <button className="icon-btn" onClick={() => setTrashOpen(true)} aria-label="Deleted files" title="Deleted files"><Trash2 size={14} /></button>
      </div>
      <input ref={upload} type="file" multiple hidden onChange={(e) => { if (e.target.files?.length) doUpload(e.target.files, uploadFolder); e.target.value = ''; }} />
      <div
        className="min-h-0 flex-1 overflow-y-auto p-1"
        role="tree"
        onDragOver={(e) => canWrite && e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); if (canWrite && e.dataTransfer.files.length) doUpload(e.dataTransfer.files, ''); }}
      >
        {tree.children.flatMap((c) => renderNode(c, 0))}
      </div>
      <NewEntryModal value={creating} manuscriptId={manuscript.id} onClose={() => setCreating(null)} onCreated={(f) => { onChanged(); if (f.file_kind === 'text') onOpen(f); }} />
      <RenameModal file={renaming} onClose={() => setRenaming(null)} onDone={(warning) => { onChanged(); if (warning) toast(warning, 'info'); }} />
      <ConfirmDialog open={Boolean(deleting)} onClose={() => setDeleting(null)} title={`Delete ${deleting?.file_kind === 'folder' ? 'folder' : 'file'}?`} danger confirmLabel="Move to Trash"
        message={`“${deleting?.path}”${deleting?.file_kind === 'folder' ? ' and everything inside it' : ''} will move to the paper's Trash. Version history is kept and you can restore it.`}
        onConfirm={async () => { if (deleting) { await api.del(`/manuscript-files/${deleting.id}`).catch(onError); onChanged(); } }} />
      <TrashModal open={trashOpen} manuscriptId={manuscript.id} canWrite={canWrite} onClose={() => setTrashOpen(false)} onRestored={onChanged} />
    </div>
  );
}

function NodeMenu({ node, isFolder, isMain, onNewFile, onNewFolder, onUpload, onRename, onDelete, onMain }: { node: Node; isFolder: boolean; isMain: boolean; onNewFile(): void; onNewFolder(): void; onUpload(): void; onRename(): void; onDelete(): void; onMain(): void }) {
  const [open, setOpen] = useState(false);
  return (
    <Dropdown open={open} setOpen={setOpen} align="right" trigger={<button className="icon-btn h-6 w-6 opacity-0 focus:opacity-100 group-hover:opacity-100" onClick={(e) => { e.stopPropagation(); setOpen(!open); }} aria-label={`Actions for ${node.path}`}><MoreHorizontal size={14} /></button>}>
      {isFolder && <button className="menu-item" onClick={onNewFile}><FilePlus2 size={14} /> New file here</button>}
      {isFolder && <button className="menu-item" onClick={onNewFolder}><FolderPlus size={14} /> New folder here</button>}
      {isFolder && <button className="menu-item" onClick={onUpload}><Upload size={14} /> Upload here</button>}
      {!isFolder && node.path.endsWith('.tex') && !isMain && <button className="menu-item" onClick={onMain}><Star size={14} /> Set as main file</button>}
      <button className="menu-item" onClick={onRename}><Pencil size={14} /> Rename / move</button>
      <button className="menu-item text-danger" onClick={onDelete} disabled={isMain}><Trash2 size={14} /> Delete</button>
    </Dropdown>
  );
}

function NewEntryModal({ value, manuscriptId, onClose, onCreated }: { value: { kind: 'text' | 'folder'; folder: string } | null; manuscriptId: string; onClose(): void; onCreated(f: ManuscriptFile): void }) {
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    if (!value) return;
    setError(null);
    const path = value.folder ? `${value.folder}/${name.trim()}` : name.trim();
    try {
      const f = await api.post<ManuscriptFile>(`/manuscripts/${manuscriptId}/files`, { path, kind: value.kind });
      setName('');
      onClose();
      onCreated(f);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create.');
    }
  };
  return (
    <Modal open={Boolean(value)} onClose={onClose} title={value?.kind === 'folder' ? 'New folder' : 'New file'}
      footer={<><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={!name.trim()} onClick={submit}>Create</button></>}>
      <label className="block">
        <span className="label">{value?.folder ? `In ${value.folder}/` : 'Name'}</span>
        <input className="input font-mono" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && submit()} placeholder={value?.kind === 'folder' ? 'figures' : 'sections/discussion.tex'} />
      </label>
      {error && <p className="mt-2 text-sm text-danger">{error}</p>}
    </Modal>
  );
}

function RenameModal({ file, onClose, onDone }: { file: ManuscriptFile | null; onClose(): void; onDone(warning?: string | null): void }) {
  const [path, setPath] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [forId, setForId] = useState<string | null>(null);
  if (file && forId !== file.id) {
    setForId(file.id);
    setPath(file.path);
    setError(null);
  }
  const submit = async () => {
    if (!file) return;
    try {
      const res = await api.patch<{ warning: string | null }>(`/manuscript-files/${file.id}`, { path });
      onClose();
      onDone(res.warning);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Rename failed.');
    }
  };
  return (
    <Modal open={Boolean(file)} onClose={onClose} title="Rename or move" footer={<><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" onClick={submit}>Save</button></>}>
      <label className="block"><span className="label">Path inside the paper</span><input className="input font-mono" value={path} onChange={(e) => setPath(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && submit()} /></label>
      <p className="mt-2 text-xs text-muted">Source is never rewritten automatically. If other files reference the old path, you'll be told which ones.</p>
      {error && <p className="mt-2 text-sm text-danger">{error}</p>}
    </Modal>
  );
}

function TrashModal({ open, manuscriptId, canWrite, onClose, onRestored }: { open: boolean; manuscriptId: string; canWrite: boolean; onClose(): void; onRestored(): void }) {
  const [items, setItems] = useState<ManuscriptFile[] | null>(null);
  const onError = useErrorToast();
  useEffect(() => {
    if (!open) return;
    setItems(null);
    api.get<{ files: ManuscriptFile[] }>(`/manuscripts/${manuscriptId}/trash`).then((r) => setItems(r.files)).catch(onError);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, manuscriptId]);
  return (
    <Modal open={open} onClose={onClose} title="Deleted files">
      {items?.length === 0 && <p className="text-sm text-muted">Nothing here.</p>}
      <div className="divide-y divide-line">
        {items?.map((f) => (
          <div key={f.id} className="flex items-center gap-2 py-2 text-sm">
            <span className="flex-1 truncate font-mono text-xs">{f.path}</span>
            <span className="text-xs text-faint">{timeAgo(f.deleted_at)}</span>
            {canWrite && <button className="btn-outline px-2 py-1 text-xs" onClick={() => api.post(`/manuscript-files/${f.id}/restore`).then(() => { setItems((all) => all?.filter((x) => x.id !== f.id) ?? null); onRestored(); }).catch(onError)}><RotateCcw size={12} /> Restore</button>}
          </div>
        ))}
      </div>
    </Modal>
  );
}
