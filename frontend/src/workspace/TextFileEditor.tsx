import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { AlertTriangle, Info, X } from 'lucide-react';
import { LatexEditor, type EditorMark, type LatexEditorHandle } from '../editor/LatexEditor';
import type { CompletionData } from '../editor/latexSupport';
import type { ManuscriptFile } from '../types';
import { api } from '../services/apiClient';
import { DiffView } from '../components/DiffView';
import { ConfirmDialog, Modal, Spinner } from '../components/ui';
import { useFileDocument, type SaveState } from './useFileDocument';

export interface TextFileEditorHandle extends LatexEditorHandle {
  save(): Promise<void>;
  ensureSaved(): Promise<void>;
  hasUnsaved(): boolean;
  discardChanges(): void;
  /** Show the newest saved text when there are no unsaved local edits (after restore or an accepted suggestion). */
  reloadIfClean(): Promise<void>;
}

export interface SaveStatus {
  state: SaveState;
  error: string | null;
  lastSavedAt: string | null;
}

interface Props {
  file: ManuscriptFile;
  canWrite: boolean;
  autosave: boolean;
  readOnlyReason?: string;
  completion: CompletionData;
  marks: EditorMark[];
  onStatus(status: SaveStatus): void;
  onTextChange(): void;
  onMarkClick(id: string): void;
  onSelectionChange(empty: boolean): void;
  commands: { saveVersion(): void; togglePanel(): void; palette(): void; comment(): void };
}

/** Editor for one text file: load, edit, autosave, and resolve save conflicts explicitly. */
export const TextFileEditor = forwardRef<TextFileEditorHandle, Props>(function TextFileEditor(props, ref) {
  const editor = useRef<LatexEditorHandle>(null);
  const doc = useFileDocument(props.file.id, props.canWrite, props.autosave, editor);
  const [comparing, setComparing] = useState(false);
  const [confirmKeep, setConfirmKeep] = useState(false);
  const { onStatus } = props;

  useEffect(() => {
    onStatus({ state: doc.state, error: doc.error, lastSavedAt: doc.lastSavedAt });
  }, [doc.state, doc.error, doc.lastSavedAt, onStatus]);

  useImperativeHandle(ref, () => ({
    focus: () => editor.current?.focus(),
    gotoLine: (l) => editor.current?.gotoLine(l),
    select: (a, b) => editor.current?.select(a, b),
    insertAtCursor: (t) => editor.current?.insertAtCursor(t),
    selection: () => editor.current?.selection() ?? { from: 0, to: 0, text: '', line: 1 },
    setContent: (t) => editor.current?.setContent(t),
    getContent: () => editor.current?.getContent() ?? '',
    save: doc.save,
    ensureSaved: doc.ensureSaved,
    hasUnsaved: doc.hasUnsaved,
    discardChanges: doc.discardChanges,
    reloadIfClean: async () => {
      if (!doc.hasUnsaved()) await doc.reloadLatest();
    },
  }));

  if (doc.state === 'loading' || !doc.initial) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-sm text-muted">
        {doc.error ? <span className="text-danger">{doc.error}</span> : <><Spinner /> Opening {props.file.path}…</>}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {doc.conflict && (
        <div className="flex flex-wrap items-center gap-2 border-b border-warn/40 bg-warn/10 px-3 py-2 text-xs" role="alert">
          <AlertTriangle size={14} className="text-warn" />
          <span className="min-w-[220px] flex-1">
            <b>{doc.conflict.updatedByName || 'Someone'}</b> saved a newer version while you were editing. Your changes are not saved yet.
          </span>
          <button className="btn-outline px-2 py-1 text-xs" onClick={() => setComparing(true)}>Compare</button>
          <button className="btn-outline px-2 py-1 text-xs" onClick={() => void doc.reloadLatest()}>Load their version</button>
          <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setConfirmKeep(true)}>Keep mine…</button>
        </div>
      )}
      {doc.remoteNotice && !doc.conflict && (
        <div className="flex items-center gap-2 border-b border-line bg-accent/5 px-3 py-1.5 text-xs text-muted" role="status">
          <Info size={13} className="text-accent" />
          <span className="flex-1">{doc.remoteNotice}</span>
          {doc.hasUnsaved() && <button className="underline" onClick={() => setComparing(true)}>Compare</button>}
          <button className="icon-btn h-5 w-5" onClick={doc.dismissNotice} aria-label="Dismiss"><X size={12} /></button>
        </div>
      )}
      {props.readOnlyReason && <div className="border-b border-line bg-raised px-3 py-1.5 text-xs text-muted">{props.readOnlyReason}</div>}
      <div className="min-h-0 flex-1">
        <LatexEditor
          ref={editor}
          initialContent={doc.initial.content}
          readOnly={!props.canWrite || Boolean(props.readOnlyReason)}
          language={/\.(tex|sty|cls|bib|ltx|bbx|cbx)$/i.test(props.file.path) ? 'latex' : 'plain'}
          completion={props.completion}
          marks={props.marks}
          onChange={(t) => {
            doc.onChange(t);
            props.onTextChange();
          }}
          onMarkClick={props.onMarkClick}
          onSelectionChange={props.onSelectionChange}
          commands={{ ...props.commands, save: () => void doc.save() }}
        />
      </div>
      <CompareModal
        open={comparing}
        onClose={() => setComparing(false)}
        mine={doc.currentText()}
        file={props.file}
        theirs={doc.conflict?.currentContent ?? null}
        theirsBy={doc.conflict?.updatedByName ?? ''}
      />
      <ConfirmDialog
        open={confirmKeep}
        onClose={() => setConfirmKeep(false)}
        title="Replace the newer version with yours?"
        danger
        confirmLabel="Keep my version"
        message={<>Your text will become the current version. {doc.conflict?.updatedByName || 'The other person'}'s version stays in History, so it can still be restored.</>}
        onConfirm={async () => {
          await doc.keepMine();
        }}
      />
    </div>
  );
});

function CompareModal({ open, onClose, mine, theirs, theirsBy, file }: { open: boolean; onClose(): void; mine: string; theirs: string | null; theirsBy: string; file: ManuscriptFile }) {
  const [latest, setLatest] = useState<string | null>(null);
  useEffect(() => {
    if (!open || theirs !== null) return;
    api.get<ManuscriptFile>(`/manuscript-files/${file.id}`).then((f) => setLatest(f.content ?? '')).catch(() => setLatest(''));
  }, [open, theirs, file.id]);
  const other = theirs ?? latest;
  return (
    <Modal wide open={open} onClose={onClose} title={`${file.path}: saved version${theirsBy ? ` by ${theirsBy}` : ''} → your edits`}>
      {other === null ? <Spinner /> : other === mine ? <p className="text-sm text-muted">No differences.</p> : (
        <>
          <div className="mb-1 grid grid-cols-2 gap-2 text-xs text-muted"><span>− Saved version</span><span>+ Your unsaved text</span></div>
          <DiffView left={other} right={mine} language={file.path} mode={window.innerWidth < 900 ? 'unified' : 'split'} height="60vh" />
        </>
      )}
    </Modal>
  );
}
