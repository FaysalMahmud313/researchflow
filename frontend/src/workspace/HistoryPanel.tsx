import { useEffect, useState } from 'react';
import { Bookmark, RotateCcw } from 'lucide-react';
import { api } from '../services/apiClient';
import { useApp } from '../lib/app';
import { timeAgo } from '../lib/text';
import type { FileVersion, ManuscriptFile } from '../types';
import { DiffView } from '../components/DiffView';
import { ConfirmDialog, Modal, Spinner, useErrorToast } from '../components/ui';

const KIND_LABEL: Record<FileVersion['version_kind'], string> = {
  auto: 'Auto snapshot', manual: 'Saved version', restore: 'Restored', import: 'Imported', initial: 'Created',
};

export function HistoryPanel({ file, canWrite, refreshKey, onSaveVersion, beforeRestore, onRestored }: { file: ManuscriptFile | null; canWrite: boolean; refreshKey: number; onSaveVersion(): void; beforeRestore(): Promise<void>; onRestored(): void }) {
  const [versions, setVersions] = useState<FileVersion[] | null>(null);
  const [compare, setCompare] = useState<{ left: FileVersion; right: FileVersion | 'current' } | null>(null);
  const [restoring, setRestoring] = useState<FileVersion | null>(null);
  const [pickLeft, setPickLeft] = useState<FileVersion | null>(null);
  const { toast } = useApp();
  const onError = useErrorToast();

  const load = () => {
    if (!file || file.file_kind !== 'text') return;
    api.get<{ versions: FileVersion[] }>(`/manuscript-files/${file.id}/versions`).then((r) => setVersions(r.versions)).catch(onError);
  };
  useEffect(() => {
    setVersions(null);
    setPickLeft(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file?.id, refreshKey]);

  if (!file || file.file_kind !== 'text') return <p className="p-3 text-xs text-muted">Open a text file to see its history.</p>;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1 border-b border-line px-2 py-1">
        <span className="mr-auto truncate text-[11px] font-semibold uppercase tracking-wide text-faint">History · {file.path}</span>
        {canWrite && <button className="btn-ghost px-2 py-1 text-xs" onClick={onSaveVersion}><Bookmark size={12} /> Save version</button>}
      </div>
      {pickLeft && <p className="bg-accent/5 px-2 py-1 text-xs text-muted">Comparing from v{pickLeft.version_number}: choose another version, or <button className="underline" onClick={() => setPickLeft(null)}>cancel</button>.</p>}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {!versions && <div className="p-3"><Spinner /></div>}
        {versions?.map((v) => (
          <div key={v.id} className="border-b border-line px-2 py-2 text-[13px]">
            <div className="flex items-center gap-2">
              <span className="chip">v{v.version_number}</span>
              <span className="min-w-0 flex-1 truncate font-medium">{v.summary || KIND_LABEL[v.version_kind]}</span>
            </div>
            <p className="mt-0.5 text-[11px] text-muted">{KIND_LABEL[v.version_kind]} · {v.author_name ?? 'system'} · {timeAgo(v.created_at)} · {v.length.toLocaleString()} chars</p>
            <div className="mt-1 flex flex-wrap gap-1">
              {pickLeft && pickLeft.id !== v.id ? (
                <button className="btn-outline px-2 py-0.5 text-xs" onClick={() => { setCompare({ left: pickLeft.version_number < v.version_number ? pickLeft : v, right: pickLeft.version_number < v.version_number ? v : pickLeft }); setPickLeft(null); }}>Compare with v{pickLeft.version_number}</button>
              ) : (
                <>
                  <button className="btn-ghost px-2 py-0.5 text-xs" onClick={() => setCompare({ left: v, right: 'current' })}>Compare to current</button>
                  <button className="btn-ghost px-2 py-0.5 text-xs" onClick={() => setPickLeft(v)}>Compare…</button>
                  {canWrite && <button className="btn-ghost px-2 py-0.5 text-xs" onClick={() => setRestoring(v)}><RotateCcw size={11} /> Restore</button>}
                </>
              )}
            </div>
          </div>
        ))}
      </div>
      <CompareModal file={file} value={compare} onClose={() => setCompare(null)} />
      <ConfirmDialog
        open={Boolean(restoring)}
        onClose={() => setRestoring(null)}
        title={`Restore version ${restoring?.version_number}?`}
        confirmLabel="Restore"
        message="The file will be changed to this version. The current text is saved as a new version first, so this can be undone from History."
        onConfirm={async () => {
          if (!restoring) return;
          try {
            await beforeRestore();
            await api.post(`/file-versions/${restoring.id}/restore`);
            onRestored();
            toast(`Restored version ${restoring.version_number}`, 'success');
            load();
          } catch (e) {
            onError(e);
          }
        }}
      />
    </div>
  );
}

function CompareModal({ file, value, onClose }: { file: ManuscriptFile; value: { left: FileVersion; right: FileVersion | 'current' } | null; onClose(): void }) {
  const [data, setData] = useState<{ left: string; right: string; left_title: string; right_title: string } | null>(null);
  const [mode, setMode] = useState<'split' | 'unified'>(window.innerWidth < 900 ? 'unified' : 'split');
  const onError = useErrorToast();
  useEffect(() => {
    if (!value) return;
    setData(null);
    const right = value.right === 'current' ? 'current' : value.right.id;
    api.get<typeof data>(`/manuscript-files/${file.id}/compare?left=${value.left.id}&right=${right}`).then(setData).catch(onError);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, file.id]);
  return (
    <Modal open={Boolean(value)} onClose={onClose} title={`${file.path}: ${data ? `${data.left_title} → ${data.right_title}` : 'Comparing…'}`} wide>
      <div className="mb-2 flex justify-end gap-1">
        <button className={`btn-ghost px-2 py-1 text-xs ${mode === 'split' ? 'bg-raised text-ink' : ''}`} onClick={() => setMode('split')}>Side by side</button>
        <button className={`btn-ghost px-2 py-1 text-xs ${mode === 'unified' ? 'bg-raised text-ink' : ''}`} onClick={() => setMode('unified')}>Unified</button>
      </div>
      {!data ? <Spinner /> : data.left === data.right ? <p className="text-sm text-muted">No differences.</p> : <DiffView left={data.left} right={data.right} language={file.path} mode={mode} height="62vh" />}
    </Modal>
  );
}
