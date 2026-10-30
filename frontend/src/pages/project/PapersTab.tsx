import { useRef, useState } from 'react';
import { Copy, FilePlus2, FileText, MoreHorizontal, RotateCcw, Trash2, Upload } from 'lucide-react';
import { api } from '../../services/apiClient';
import { href, navigate, useApp, useLoad } from '../../lib/app';
import { timeAgo } from '../../lib/text';
import { MANUSCRIPT_STATUSES, OWNER_ONLY_STATUSES, type Manuscript, type Project } from '../../types';
import { ConfirmDialog, Dropdown, EmptyState, Modal, SkeletonRows, Spinner, StatusBadge, useErrorToast } from '../../components/ui';

const TEMPLATES = [
  { id: 'article', name: 'Article', detail: 'Standard paper with abstract and the usual sections' },
  { id: 'structured', name: 'Multi-file paper', detail: 'main.tex with one file per section and a figures folder' },
  { id: 'ieee', name: 'IEEE conference', detail: 'IEEEtran two-column conference layout' },
  { id: 'blank', name: 'Blank', detail: 'Only \\documentclass and \\begin{document}' },
];

const REVIEW_LABEL: Record<string, string> = { draft: '', in_review: 'Ready for review', changes_requested: 'Changes requested', approved: 'Approved' };

export function PapersTab({ project }: { project: Project }) {
  const [showTrash, setShowTrash] = useState(false);
  const { data, loading, reload } = useLoad<{ manuscripts: Manuscript[] }>(`/projects/${project.id}/manuscripts?include_deleted=${showTrash}`);
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [toDelete, setToDelete] = useState<Manuscript | null>(null);
  const { toast } = useApp();
  const onError = useErrorToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const canWrite = project.my_role === 'owner' || project.my_role === 'editor';
  const isOwner = project.my_role === 'owner';

  const items = (data?.manuscripts ?? []).filter((m) => (showTrash ? m.is_deleted : !m.is_deleted));

  const importFile = async (file: File) => {
    setImporting(true);
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await api.form<Manuscript & { stored_only?: boolean; message?: string }>(`/projects/${project.id}/manuscripts/import`, form);
      if (res.stored_only) {
        toast(res.message ?? 'Saved as a project file.', 'info');
        return;
      }
      if (res.warnings?.length) toast(`Imported with notes: ${res.warnings.join(' ')}`, 'info');
      else toast('Paper imported', 'success');
      navigate({ name: 'workspace', manuscriptId: res.id });
    } catch (e) {
      onError(e);
    } finally {
      setImporting(false);
    }
  };

  const setStatus = async (m: Manuscript, status: string) => {
    try {
      await api.patch(`/manuscripts/${m.id}/status`, { status });
      reload();
    } catch (e) {
      onError(e);
    }
  };

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="mr-auto font-semibold">{showTrash ? 'Trash' : 'Papers'}</h2>
        <button className="btn-ghost" onClick={() => setShowTrash(!showTrash)}>{showTrash ? 'Back to papers' : <><Trash2 size={14} /> Trash</>}</button>
        {canWrite && !showTrash && (
          <>
            <input ref={fileInput} type="file" hidden accept=".zip,.tex,.bib,.md,.markdown,.docx,.pdf" onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} />
            <button className="btn-outline" disabled={importing} onClick={() => fileInput.current?.click()}>{importing ? <Spinner size={14} /> : <Upload size={14} />} Import</button>
            <button className="btn-primary" onClick={() => setCreating(true)}><FilePlus2 size={14} /> New paper</button>
          </>
        )}
      </div>
      {loading && !data && <SkeletonRows />}
      {data && items.length === 0 && (
        <div className="card">
          <EmptyState icon={<FileText size={26} />} title={showTrash ? 'Trash is empty' : 'No papers yet'}>
            {!showTrash && 'Start from a template or import a LaTeX project (.zip), .tex, .bib, Markdown or Word file. Uploaded originals are kept under Files & data. PDFs are stored as documents.'}
          </EmptyState>
        </div>
      )}
      {items.length > 0 && (
        <div className="card divide-y divide-line">
          {items.map((m) => (
            <div key={m.id} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
              <FileText size={16} className="text-muted" />
              <div className="min-w-0 flex-1">
                {m.is_deleted ? <span className="font-medium">{m.title}</span> : <a href={href({ name: 'workspace', manuscriptId: m.id })} className="font-medium hover:text-accent">{m.title}</a>}
                <div className="text-xs text-muted">
                  edited {timeAgo(m.updated_at)}{m.last_editor_name ? ` by ${m.last_editor_name}` : ''}
                  {REVIEW_LABEL[m.review_status] && <span className="ml-2 chip">{REVIEW_LABEL[m.review_status]}</span>}
                </div>
              </div>
              {canWrite && !m.is_deleted ? (
                <select className="input w-auto py-1 text-xs" value={m.status} onChange={(e) => setStatus(m, e.target.value)} aria-label="Paper status">
                  {MANUSCRIPT_STATUSES.map((s) => (
                    <option key={s} value={s} disabled={OWNER_ONLY_STATUSES.has(s) && !isOwner}>{s}{OWNER_ONLY_STATUSES.has(s) && !isOwner ? ' (owner)' : ''}</option>
                  ))}
                </select>
              ) : (
                <StatusBadge status={m.status} />
              )}
              {canWrite && (m.is_deleted ? (
                <button className="btn-outline" onClick={() => api.post(`/manuscripts/${m.id}/restore`).then(reload).catch(onError)}><RotateCcw size={14} /> Restore</button>
              ) : (
                <PaperMenu m={m} onDelete={() => setToDelete(m)} onCopied={(id) => navigate({ name: 'workspace', manuscriptId: id })} />
              ))}
            </div>
          ))}
        </div>
      )}
      <CreatePaperModal open={creating} onClose={() => setCreating(false)} projectId={project.id} />
      <ConfirmDialog
        open={Boolean(toDelete)}
        onClose={() => setToDelete(null)}
        title="Move paper to Trash?"
        message={<>“{toDelete?.title}” will be moved to Trash. The project and its other papers are not affected, and you can restore it later.</>}
        confirmLabel="Move to Trash"
        danger
        onConfirm={async () => {
          if (!toDelete) return;
          await api.del(`/manuscripts/${toDelete.id}`).catch(onError);
          reload();
        }}
      />
    </div>
  );
}

function PaperMenu({ m, onDelete, onCopied }: { m: Manuscript; onDelete(): void; onCopied(id: string): void }) {
  const [open, setOpen] = useState(false);
  const onError = useErrorToast();
  return (
    <Dropdown open={open} setOpen={setOpen} align="right" trigger={<button className="icon-btn" onClick={() => setOpen(!open)} aria-label="Paper actions"><MoreHorizontal size={16} /></button>}>
      <button className="menu-item" onClick={() => api.post<Manuscript>(`/manuscripts/${m.id}/copy`, { title: `${m.title} (revision)` }).then((r) => onCopied(r.id)).catch(onError)}>
        <Copy size={14} /> Create revision copy
      </button>
      <button className="menu-item text-danger" onClick={onDelete}><Trash2 size={14} /> Move to Trash</button>
    </Dropdown>
  );
}

function CreatePaperModal({ open, onClose, projectId }: { open: boolean; onClose(): void; projectId: string }) {
  const [title, setTitle] = useState('');
  const [template, setTemplate] = useState('article');
  const [compiler, setCompiler] = useState('pdflatex');
  const [busy, setBusy] = useState(false);
  const onError = useErrorToast();
  const create = async () => {
    setBusy(true);
    try {
      const m = await api.post<Manuscript>(`/projects/${projectId}/manuscripts`, { title, template, compiler });
      onClose();
      navigate({ name: 'workspace', manuscriptId: m.id });
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onClose={onClose} title="New paper"
      footer={<><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={busy || title.trim().length < 2} onClick={create}>{busy && <Spinner size={14} />} Create paper</button></>}>
      <div className="space-y-3">
        <label className="block"><span className="label">Title</span><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} /></label>
        <div>
          <span className="label">Template</span>
          <div className="grid gap-2 sm:grid-cols-2">
            {TEMPLATES.map((t) => (
              <button key={t.id} type="button" onClick={() => setTemplate(t.id)} className={`rounded-lg border p-2.5 text-left ${template === t.id ? 'border-accent bg-accent/5' : 'border-line hover:bg-raised'}`}>
                <span className="block text-[13px] font-medium">{t.name}</span>
                <span className="block text-xs text-muted">{t.detail}</span>
              </button>
            ))}
          </div>
        </div>
        <label className="block"><span className="label">TeX engine (named in the export instructions)</span>
          <select className="input" value={compiler} onChange={(e) => setCompiler(e.target.value)}>
            <option value="pdflatex">pdfLaTeX</option><option value="xelatex">XeLaTeX</option><option value="lualatex">LuaLaTeX</option>
          </select>
        </label>
      </div>
    </Modal>
  );
}
