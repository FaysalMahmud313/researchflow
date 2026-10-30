import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { api, ApiError } from '../services/apiClient';
import type { LatexEditorHandle } from '../editor/LatexEditor';
import type { ManuscriptFile } from '../types';

export type SaveState = 'loading' | 'saved' | 'unsaved' | 'saving' | 'error' | 'conflict';

export interface Conflict {
  currentContent: string;
  currentRevision: number;
  updatedByName: string;
  updatedAt: string;
}

const AUTOSAVE_DELAY_MS = 2000;
const REMOTE_CHECK_MS = 20000;

/**
 * Load and save one text file with optimistic concurrency.
 *
 * Every save sends the revision it was based on. If someone else saved in between, the
 * server answers 409 and this hook enters the `conflict` state: nothing is overwritten
 * until the user compares and chooses to reload theirs or keep their own version.
 */
export function useFileDocument(fileId: string, canWrite: boolean, autosave: boolean, editor: RefObject<LatexEditorHandle>) {
  const [state, setState] = useState<SaveState>('loading');
  const [initial, setInitial] = useState<{ content: string; revision: number } | null>(null);
  const [conflict, setConflict] = useState<Conflict | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);
  const [remoteNotice, setRemoteNotice] = useState<string | null>(null);
  const revision = useRef(0);
  const savedContent = useRef('');
  const latest = useRef('');
  const saving = useRef<Promise<void> | null>(null);
  const timer = useRef<number | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  const load = useCallback(async () => {
    const f = await api.get<ManuscriptFile>(`/manuscript-files/${fileId}`);
    revision.current = f.revision;
    savedContent.current = f.content ?? '';
    latest.current = f.content ?? '';
    setLastSavedAt(f.updated_at);
    return f;
  }, [fileId]);

  useEffect(() => {
    let cancelled = false;
    setState('loading');
    setConflict(null);
    load()
      .then((f) => {
        if (cancelled) return;
        setInitial({ content: f.content ?? '', revision: f.revision });
        setState('saved');
      })
      .catch((e) => !cancelled && (setError(e instanceof Error ? e.message : 'Could not open the file.'), setState('error')));
    return () => {
      cancelled = true;
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [load]);

  const doSave = useCallback(
    async (baseRevision: number): Promise<void> => {
      const content = latest.current;
      setState('saving');
      try {
        const res = await api.putJson<{ revision: number; updated_at: string }>(`/manuscript-files/${fileId}/content`, {
          content,
          base_revision: baseRevision,
        });
        revision.current = res.revision;
        savedContent.current = content;
        setLastSavedAt(res.updated_at);
        setConflict(null);
        setError(null);
        setState(latest.current === content ? 'saved' : 'unsaved');
      } catch (e) {
        if (e instanceof ApiError && e.status === 409 && e.detail && typeof e.detail === 'object') {
          const d = e.detail as { current_content: string; current_revision: number; updated_by_name: string; updated_at: string };
          setConflict({ currentContent: d.current_content, currentRevision: d.current_revision, updatedByName: d.updated_by_name, updatedAt: d.updated_at });
          setState('conflict');
        } else {
          setError(e instanceof Error ? e.message : 'Save failed.');
          setState('error');
        }
      }
    },
    [fileId],
  );

  const save = useCallback(async (): Promise<void> => {
    if (!canWrite || stateRef.current === 'conflict' || stateRef.current === 'loading') return;
    if (timer.current) window.clearTimeout(timer.current);
    if (saving.current) await saving.current;
    if (latest.current === savedContent.current) {
      setState('saved');
      return;
    }
    saving.current = doSave(revision.current).finally(() => {
      saving.current = null;
    });
    await saving.current;
  }, [canWrite, doSave]);

  const onChange = useCallback(
    (text: string) => {
      latest.current = text;
      if (stateRef.current === 'conflict') return;
      const dirty = text !== savedContent.current;
      setState(dirty ? 'unsaved' : 'saved');
      if (timer.current) window.clearTimeout(timer.current);
      if (dirty && autosave && canWrite) timer.current = window.setTimeout(() => void save(), AUTOSAVE_DELAY_MS);
    },
    [autosave, canWrite, save],
  );

  /** Replace local text with the newest saved version (discarding unsaved edits). */
  const reloadLatest = useCallback(async () => {
    const f = await load();
    editor.current?.setContent(f.content ?? '');
    setConflict(null);
    setRemoteNotice(null);
    setState('saved');
  }, [load, editor]);

  /** Explicitly keep my text over a newer version the user has just reviewed. */
  const keepMine = useCallback(async () => {
    if (!conflict) return;
    await doSave(conflict.currentRevision);
  }, [conflict, doSave]);

  /** Cancel: throw away unsaved edits and return to the last saved text. */
  const discardChanges = useCallback(() => {
    editor.current?.setContent(savedContent.current);
    latest.current = savedContent.current;
    if (timer.current) window.clearTimeout(timer.current);
    setState('saved');
  }, [editor]);

  /** Resolve once everything typed so far is saved; throws if that is not possible. */
  const ensureSaved = useCallback(async () => {
    if (latest.current !== savedContent.current) await save();
    if (latest.current !== savedContent.current || stateRef.current === 'conflict' || stateRef.current === 'error') {
      throw new Error('Save your changes (or resolve the conflict) first.');
    }
  }, [save]);

  // Notice newer saves by other people. With no local edits, quietly switch to their version.
  useEffect(() => {
    if (state === 'loading') return;
    const check = async () => {
      if (document.hidden || saving.current) return;
      try {
        const f = await api.get<ManuscriptFile & { updated_by_name?: string }>(`/manuscript-files/${fileId}`);
        if (f.revision <= revision.current) return;
        if (latest.current === savedContent.current) {
          revision.current = f.revision;
          savedContent.current = f.content ?? '';
          latest.current = f.content ?? '';
          editor.current?.setContent(f.content ?? '');
          setLastSavedAt(f.updated_at);
          setRemoteNotice(`Updated to the latest version saved by ${f.updated_by_name || 'a collaborator'}.`);
        } else {
          setRemoteNotice(`${f.updated_by_name || 'A collaborator'} saved a newer version. Saving will ask you to compare first.`);
        }
      } catch {
        /* offline or file removed: the next save reports it */
      }
    };
    const t = window.setInterval(check, REMOTE_CHECK_MS);
    return () => window.clearInterval(t);
  }, [fileId, state, editor]);

  return {
    state,
    initial,
    conflict,
    error,
    lastSavedAt,
    remoteNotice,
    dismissNotice: () => setRemoteNotice(null),
    hasUnsaved: () => latest.current !== savedContent.current,
    currentText: () => latest.current,
    onChange,
    save,
    reloadLatest,
    keepMine,
    discardChanges,
    ensureSaved,
  };
}
