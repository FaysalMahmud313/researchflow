import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import {
  AlertCircle, ArrowLeft, BookOpen, CheckCircle2, ChevronDown, CircleDashed, Columns2, Command, Download, Files, FileCode2,
  History, Image as ImageIcon, Keyboard, ListTree, Lock, MessageSquare, MessageSquarePlus, PanelLeft, PanelRight, Pencil, Quote,
  RotateCcw, Save, Search, Sigma, Table2, Wand2, Wrench,
} from 'lucide-react';
import { api, ApiError, downloadFile, saveBlob } from '../services/apiClient';
import { href, navigate, useApp } from '../lib/app';
import { utf16ToCodePoint, timeAgo } from '../lib/text';
import { locateAnchor } from '../lib/anchors';
import type { EditorMark } from '../editor/LatexEditor';
import type { CompletionData } from '../editor/latexSupport';
import { MANUSCRIPT_STATUSES, OWNER_ONLY_STATUSES, type CitationIndex, type DocComment, type Manuscript, type ManuscriptFile, type Suggestion } from '../types';
import { Dropdown, Modal, Spinner, StatusBadge, useErrorToast } from '../components/ui';
import { SHORTCUTS } from '../pages/SettingsPage';
import { TextFileEditor, type SaveStatus, type TextFileEditorHandle } from './TextFileEditor';
import { FileTree } from './FileTree';
import { OutlinePanel } from './OutlinePanel';
import { ReviewPanel } from './ReviewPanel';
import { HistoryPanel } from './HistoryPanel';
import { SearchPanel } from './SearchPanel';
import { DocumentTools, type DependencyReport, type ToolAction } from './DocumentTools';
import { CommandPalette, type PaletteItem } from './CommandPalette';
import { CommentDialog, InsertDialog, SuggestDialog, type InsertKind } from './InsertDialogs';

type ViewMode = 'split' | 'editor' | 'panel';
type LeftTab = 'files' | 'outline' | 'search';
type RightTab = 'tools' | 'review' | 'history';
type MobilePane = 'files' | 'editor' | 'tools' | 'review';

interface Prefs {
  leftWidth: number;
  rightWidth: number;
  leftCollapsed: boolean;
  rightCollapsed: boolean;
  view: ViewMode;
  autosave: boolean;
  leftTab: LeftTab;
  rightTab: RightTab;
}

const DEFAULT_PREFS: Prefs = { leftWidth: 240, rightWidth: 360, leftCollapsed: false, rightCollapsed: false, view: 'split', autosave: true, leftTab: 'files', rightTab: 'tools' };

/** Per-user layout preferences: applied instantly from localStorage, then synced from/to the server. */
function useWorkspacePrefs(): [Prefs, (patch: Partial<Prefs>) => void] {
  const [prefs, setPrefs] = useState<Prefs>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('rf_workspace_prefs') || '{}');
      return { ...DEFAULT_PREFS, ...saved, rightTab: ['tools', 'review', 'history'].includes(saved.rightTab) ? saved.rightTab : 'tools' };
    } catch {
      return DEFAULT_PREFS;
    }
  });
  const saveTimer = useRef<number | null>(null);
  useEffect(() => {
    api.get<{ prefs: Partial<Prefs> }>('/users/me/workspace-preferences').then((r) => setPrefs((p) => ({
      ...p, ...r.prefs, rightTab: ['tools', 'review', 'history'].includes(r.prefs.rightTab ?? '') ? (r.prefs.rightTab as RightTab) : p.rightTab,
    }))).catch(() => undefined);
  }, []);
  const update = useCallback((patch: Partial<Prefs>) => {
    setPrefs((p) => {
      const next = { ...p, ...patch };
      try {
        localStorage.setItem('rf_workspace_prefs', JSON.stringify(next));
      } catch {
        /* ignore */
      }
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(() => api.patch('/users/me/workspace-preferences', { prefs: next }).catch(() => undefined), 800);
      return next;
    });
  }, []);
  return [prefs, update];
}

function useIsMobile(): boolean {
  const [mobile, setMobile] = useState(() => window.innerWidth < 768);
  useEffect(() => {
    const fn = () => setMobile(window.innerWidth < 768);
    window.addEventListener('resize', fn);
    return () => window.removeEventListener('resize', fn);
  }, []);
  return mobile;
}

function SaveIndicator({ status, canWrite }: { status: SaveStatus | null; canWrite: boolean }) {
  if (!status) return null;
  if (!canWrite) return <span className="chip"><Lock size={11} /> Read only</span>;
  const map: Record<SaveStatus['state'], { icon: JSX.Element; text: string; cls: string }> = {
    loading: { icon: <CircleDashed size={13} className="animate-spin" />, text: 'Opening…', cls: 'text-muted' },
    saved: { icon: <CheckCircle2 size={13} />, text: 'Saved', cls: 'text-success' },
    unsaved: { icon: <CircleDashed size={13} />, text: 'Unsaved changes', cls: 'text-muted' },
    saving: { icon: <Spinner size={12} />, text: 'Saving…', cls: 'text-muted' },
    error: { icon: <AlertCircle size={13} />, text: 'Save failed', cls: 'text-danger' },
    conflict: { icon: <AlertCircle size={13} />, text: 'Newer version exists', cls: 'text-warn' },
  };
  const m = map[status.state];
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap text-xs ${m.cls}`} role="status" aria-live="polite"
      title={status.error || (status.lastSavedAt ? `Last saved ${timeAgo(status.lastSavedAt)}` : '')}>
      {m.icon} <span className="hidden md:inline">{m.text}</span>
    </span>
  );
}

function ResizeHandle({ onDrag, label }: { onDrag(dx: number): void; label: string }) {
  const onPointerDown = (e: ReactPointerEvent) => {
    e.preventDefault();
    let last = e.clientX;
    const move = (ev: PointerEvent) => {
      onDrag(ev.clientX - last);
      last = ev.clientX;
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      document.body.style.cursor = '';
    };
    document.body.style.cursor = 'col-resize';
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return (
    <div role="separator" aria-orientation="vertical" aria-label={label} tabIndex={0} onPointerDown={onPointerDown}
      onKeyDown={(e) => { if (e.key === 'ArrowLeft') onDrag(-24); if (e.key === 'ArrowRight') onDrag(24); }}
      className="w-1 shrink-0 cursor-col-resize bg-line/60 transition-colors hover:bg-accent/60 focus:bg-accent" />
  );
}

/** Previews uploaded binary assets: images inline, PDFs in the browser's own viewer, anything else as a download. */
function AssetPreview({ file, onDownload }: { file: ManuscriptFile; onDownload(): void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const previewable = file.media_type.startsWith('image/') || file.media_type === 'application/pdf';
  useEffect(() => {
    if (!previewable) return;
    let objectUrl: string | null = null;
    api.blob(`/manuscript-files/${file.id}/raw?inline=true`)
      .then(({ blob }) => {
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => setFailed(true));
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [file.id, previewable]);
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-end border-b border-line px-2 py-1">
        <button className="btn-ghost px-2 py-1 text-xs" onClick={onDownload}><Download size={13} /> Download</button>
      </div>
      <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto p-4">
        {!previewable || failed ? (
          <p className="text-sm text-muted">No preview for this file type. Download it to open it.</p>
        ) : !url ? <Spinner /> : file.media_type === 'application/pdf' ? (
          <iframe title={file.path} src={url} className="h-full w-full rounded border border-line bg-white" />
        ) : (
          <img src={url} alt={file.path} className="max-h-full max-w-full rounded border border-line bg-white" />
        )}
      </div>
    </div>
  );
}

export default function WorkspacePage({ manuscriptId, initialFileId }: { manuscriptId: string; initialFileId?: string }) {
  const { toast } = useApp();
  const onError = useErrorToast();
  const isMobile = useIsMobile();
  const [prefs, setPrefs] = useWorkspacePrefs();
  const [mobilePane, setMobilePane] = useState<MobilePane>('editor');

  const [manuscript, setManuscript] = useState<Manuscript | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(initialFileId ?? null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus | null>(null);
  const [textVersion, setTextVersion] = useState(0);
  const [index, setIndex] = useState<CitationIndex | null>(null);
  const [threads, setThreads] = useState<DocComment[]>([]);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [focusReview, setFocusReview] = useState<string | null>(null);
  const [historyKey, setHistoryKey] = useState(0);
  const [hasSelection, setHasSelection] = useState(false);
  const [dialog, setDialog] = useState<InsertKind>(null);
  const [commentDraft, setCommentDraft] = useState<{ from: number; to: number; text: string; line: number } | null>(null);
  const [suggestDraft, setSuggestDraft] = useState<{ from: number; to: number; text: string; line: number } | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [searchFocus, setSearchFocus] = useState(0);
  const [toolBusy, setToolBusy] = useState<ToolAction | null>(null);
  const [depsReport, setDepsReport] = useState<DependencyReport | null>(null);

  const editorRef = useRef<TextFileEditorHandle>(null);
  const completion = useRef<CompletionData>({ index: null }).current;
  const textTimer = useRef<number | null>(null);

  const role = manuscript?.my_role;
  const canWrite = role === 'owner' || role === 'editor';
  const canComment = canWrite || role === 'reviewer';
  const files = useMemo(() => manuscript?.files ?? [], [manuscript]);
  const activeFile = files.find((f) => f.id === activeId) ?? null;

  // ---------------------------------------------------------------- loading
  const loadManuscript = useCallback(async () => {
    try {
      const m = await api.get<Manuscript>(`/manuscripts/${manuscriptId}`);
      setManuscript(m);
      setActiveId((cur) => (cur && m.files?.some((f) => f.id === cur) ? cur : m.files?.find((f) => f.path === m.main_file_path)?.id ?? m.files?.find((f) => f.file_kind === 'text')?.id ?? null));
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'Could not open this paper.');
    }
  }, [manuscriptId]);
  useEffect(() => {
    loadManuscript();
  }, [loadManuscript]);

  const loadIndex = useCallback(() => {
    api.get<CitationIndex>(`/manuscripts/${manuscriptId}/index`).then((idx) => {
      completion.index = idx;
      setIndex(idx);
    }).catch(() => undefined);
  }, [manuscriptId, completion]);
  const loadReview = useCallback(() => {
    api.get<{ threads: DocComment[] }>(`/manuscripts/${manuscriptId}/comments`).then((r) => setThreads(r.threads)).catch(() => undefined);
    api.get<{ suggestions: Suggestion[] }>(`/manuscripts/${manuscriptId}/suggestions?status=pending`).then((r) => setSuggestions(r.suggestions)).catch(() => undefined);
  }, [manuscriptId]);
  useEffect(() => {
    loadIndex();
    loadReview();
    const t = window.setInterval(() => {
      loadIndex();
      loadReview();
    }, 60000);
    return () => window.clearInterval(t);
  }, [loadIndex, loadReview]);
  useEffect(() => {
    if (saveStatus?.state === 'saved' && textVersion > 0) loadIndex();
  }, [saveStatus?.state, textVersion, loadIndex]);

  useEffect(() => {
    if (activeId) navigate({ name: 'workspace', manuscriptId, fileId: activeId }, true);
  }, [activeId, manuscriptId]);

  // ---------------------------------------------------------------- unsaved-change protection
  useEffect(() => {
    const onUnload = (e: BeforeUnloadEvent) => {
      if (editorRef.current?.hasUnsaved()) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', onUnload);
    return () => window.removeEventListener('beforeunload', onUnload);
  }, []);

  /** Save before leaving the current file; ask if saving is not possible. */
  const leaveFile = useCallback(async (): Promise<boolean> => {
    const ed = editorRef.current;
    if (!ed || !ed.hasUnsaved()) return true;
    try {
      await ed.ensureSaved();
      return true;
    } catch {
      return window.confirm('Your latest changes could not be saved. Leave this file and discard them?');
    }
  }, []);

  const ensureSaved = useCallback(async () => {
    await editorRef.current?.ensureSaved();
  }, []);

  // ---------------------------------------------------------------- comment & suggestion marks
  const marks = useMemo<EditorMark[]>(() => {
    const text = editorRef.current?.getContent();
    if (!text || !activeFile) return [];
    const out: EditorMark[] = [];
    for (const t of threads) {
      if (t.file_id !== activeFile.id || t.status !== 'open') continue;
      const span = locateAnchor(text, t.anchor, t.quoted_text);
      if (span) out.push({ id: t.id, kind: 'comment', title: `${t.author_name}: ${t.body}`, ...span });
    }
    for (const s of suggestions) {
      if (s.file_id !== activeFile.id) continue;
      const span = locateAnchor(text, s.anchor, s.original_text);
      if (span) out.push({ id: s.id, kind: 'suggestion', title: `${s.author_name} suggests: ${s.proposed_text}`, ...span });
    }
    return out;
    // textVersion: recompute positions as the text changes (debounced).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threads, suggestions, activeFile?.id, textVersion, saveStatus?.state]);

  const anchorFor = (sel: { from: number; to: number; line: number }) => {
    const text = editorRef.current?.getContent() ?? '';
    return {
      from: utf16ToCodePoint(text, sel.from),
      to: utf16ToCodePoint(text, sel.to),
      line: sel.line,
      context_before: text.slice(Math.max(0, sel.from - 40), sel.from),
      context_after: text.slice(sel.to, sel.to + 40),
    };
  };

  const startComment = () => {
    if (!canComment) return;
    const sel = editorRef.current?.selection();
    if (!sel || sel.from === sel.to) {
      toast('Select the text you want to comment on.', 'info');
      return;
    }
    setCommentDraft(sel);
  };
  const startSuggest = () => {
    const sel = editorRef.current?.selection();
    if (!sel || sel.from === sel.to) {
      toast('Select the text you want to change, then choose Suggest edit.', 'info');
      return;
    }
    setSuggestDraft(sel);
  };

  // ---------------------------------------------------------------- actions
  const saveNow = useCallback(async () => {
    if (!editorRef.current) return;
    await editorRef.current.save();
  }, []);

  const saveVersion = useCallback(async () => {
    if (!activeFile || !canWrite) return;
    try {
      await ensureSaved();
      await api.post(`/manuscript-files/${activeFile.id}/versions`, { summary: `Saved ${new Date().toLocaleString()}` });
      setHistoryKey((k) => k + 1);
      toast('Version saved', 'success');
    } catch (e) {
      onError(e);
    }
  }, [activeFile, canWrite, ensureSaved, toast, onError]);

  const openFile = async (f: ManuscriptFile, line?: number) => {
    if (f.id !== activeId && !(await leaveFile())) return;
    setActiveId(f.id);
    if (isMobile) setMobilePane('editor');
    if (line) window.setTimeout(() => editorRef.current?.gotoLine(line), f.id === activeId ? 0 : 700);
  };

  const jumpToReview = (fileId: string | null, item: DocComment | Suggestion) => {
    const f = files.find((x) => x.id === fileId);
    if (!f) return;
    const quoted = 'quoted_text' in item ? item.quoted_text : item.original_text;
    const go = () => {
      const text = editorRef.current?.getContent() ?? '';
      const span = locateAnchor(text, item.anchor, quoted);
      if (span) editorRef.current?.select(span.from, span.to);
      else if (item.anchor.line) editorRef.current?.gotoLine(item.anchor.line);
    };
    if (f.id === activeId) go();
    else {
      void openFile(f);
      window.setTimeout(go, 900);
    }
  };

  const runTool = async (action: ToolAction) => {
    setToolBusy(action);
    try {
      if (['zip', 'flat', 'file', 'bib', 'deps', 'sync-bib'].includes(action)) await ensureSaved();
      if (action === 'zip') {
        const headers = await downloadFile(`/manuscripts/${manuscriptId}/export/project.zip`, 'paper.zip');
        const missing = Number(headers.get('X-Export-Missing') || 0);
        toast(missing ? `Downloaded. ${missing} referenced file(s) are missing; they are listed in the README.` : 'LaTeX project downloaded.', missing ? 'info' : 'success');
      } else if (action === 'flat') {
        const headers = await downloadFile(`/manuscripts/${manuscriptId}/export/paper.tex`, 'paper.tex');
        const warnings = JSON.parse(headers.get('X-Export-Warnings') || '[]') as string[];
        if (warnings.length) toast(warnings.join(' '), 'info');
      } else if (action === 'file' && activeFile) {
        await downloadFile(`/manuscript-files/${activeFile.id}/raw`, activeFile.path.split('/').pop() || 'file.tex');
      } else if (action === 'bib') {
        await downloadFile(`/manuscripts/${manuscriptId}/export/bibliography.bib`, 'references.bib');
      } else if (action === 'assets') {
        await downloadFile(`/manuscripts/${manuscriptId}/export/assets.zip`, 'assets.zip');
      } else if (action === 'copy-selection' || action === 'save-selection') {
        const sel = editorRef.current?.selection();
        if (!sel?.text) {
          toast('Select some LaTeX in the editor first.', 'info');
        } else if (action === 'copy-selection') {
          await navigator.clipboard.writeText(sel.text);
          toast('Selection copied as LaTeX', 'success');
        } else saveBlob(new Blob([sel.text + '\n'], { type: 'text/plain' }), 'selection.tex');
      } else if (action === 'section') {
        setPrefs({ leftTab: 'outline', leftCollapsed: false });
        if (isMobile) setMobilePane('files');
      } else if (action === 'deps') {
        setDepsReport(await api.get<DependencyReport>(`/manuscripts/${manuscriptId}/dependencies`));
      } else if (action === 'sync-bib') {
        const bib = files.find((f) => f.file_kind === 'text' && f.path.endsWith('.bib'));
        if (!bib) {
          await api.post(`/manuscripts/${manuscriptId}/files`, { path: 'references.bib', kind: 'text', content: '' });
          await loadManuscript();
        }
        const res = await api.post<{ added: number; path: string }>(`/manuscripts/${manuscriptId}/bibliography/sync`, { path: bib?.path ?? 'references.bib', mode: 'merge' });
        toast(res.added ? `Added ${res.added} references to ${res.path}` : `${res.path} already has every project reference`, 'success');
        loadIndex();
        await editorRef.current?.reloadIfClean();
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) toast(e.message, 'info');
      else onError(e);
    } finally {
      setToolBusy(null);
    }
  };

  const updateSetting = (patch: { main_file_path?: string; compiler?: string }) =>
    api.patch<Manuscript>(`/manuscripts/${manuscriptId}`, patch).then((m) => setManuscript((cur) => (cur ? { ...cur, main_file_path: m.main_file_path, compiler: m.compiler } : cur))).catch(onError);

  const insert = (text: string) => {
    editorRef.current?.insertAtCursor(text);
    setDialog(null);
  };

  const togglePanel = useCallback(() => setPrefs({ rightCollapsed: !prefs.rightCollapsed, view: prefs.view === 'editor' ? 'split' : prefs.view }), [prefs.rightCollapsed, prefs.view, setPrefs]);
  const editorCommands = useMemo(() => ({
    saveVersion: () => void saveVersion(),
    togglePanel,
    palette: () => setPaletteOpen(true),
    comment: startComment,
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [saveVersion, togglePanel, canComment]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      const inEditor = (e.target as HTMLElement)?.closest?.('.cm-editor');
      if (e.key.toLowerCase() === 'k' && !inEditor) { e.preventDefault(); setPaletteOpen(true); }
      else if (e.shiftKey && e.key.toLowerCase() === 'f') { e.preventDefault(); setPrefs({ leftTab: 'search', leftCollapsed: false }); setSearchFocus((n) => n + 1); }
      else if (e.key.toLowerCase() === 's' && !inEditor && !e.shiftKey) { e.preventDefault(); void saveNow(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [saveNow, setPrefs]);

  const onTextChange = useCallback(() => {
    if (textTimer.current) window.clearTimeout(textTimer.current);
    textTimer.current = window.setTimeout(() => setTextVersion((v) => v + 1), 400);
  }, []);

  const paletteItems: PaletteItem[] = [
    ...files.filter((f) => f.file_kind !== 'folder').map((f) => ({ id: f.id, label: f.path, kind: 'file' as const, run: () => void openFile(f) })),
    { id: 'save', label: 'Save', hint: 'Ctrl+S', kind: 'action', run: () => void saveNow() },
    { id: 'version', label: 'Save a named version', hint: 'Ctrl+Shift+S', kind: 'action', run: () => void saveVersion() },
    { id: 'zip', label: 'Download LaTeX project (.zip)', kind: 'action', run: () => void runTool('zip') },
    { id: 'flat', label: 'Export full paper as one .tex', kind: 'action', run: () => void runTool('flat') },
    { id: 'search', label: 'Search in all files', hint: 'Ctrl+Shift+F', kind: 'action', run: () => { setPrefs({ leftTab: 'search', leftCollapsed: false }); setSearchFocus((n) => n + 1); } },
    { id: 'figure', label: 'Insert figure', kind: 'action', run: () => setDialog('figure') },
    { id: 'table', label: 'Insert table', kind: 'action', run: () => setDialog('table') },
    { id: 'equation', label: 'Insert equation', kind: 'action', run: () => setDialog('equation') },
    { id: 'cite', label: 'Insert citation', kind: 'action', run: () => setDialog('cite') },
    { id: 'deps', label: 'Check missing files and citations', kind: 'action', run: () => { setPrefs({ rightTab: 'tools', rightCollapsed: false }); void runTool('deps'); } },
    { id: 'help', label: 'Keyboard shortcuts', kind: 'action', run: () => setHelpOpen(true) },
  ];

  // ---------------------------------------------------------------- render
  if (loadError) {
    return <div className="mx-auto max-w-md p-8 text-center"><p className="font-medium">Can't open this paper</p><p className="mt-1 text-sm text-muted">{loadError}</p><a className="btn-outline mt-4" href="#/">Back</a></div>;
  }
  if (!manuscript) return <div className="flex h-full items-center justify-center"><Spinner size={20} /></div>;

  const showLeft = isMobile ? mobilePane === 'files' : !prefs.leftCollapsed && prefs.view !== 'panel';
  const showEditor = isMobile ? mobilePane === 'editor' : prefs.view !== 'panel';
  const showRight = isMobile ? mobilePane === 'tools' || mobilePane === 'review' : !prefs.rightCollapsed && prefs.view !== 'editor';
  const rightTab: RightTab = isMobile ? (mobilePane === 'review' ? 'review' : 'tools') : prefs.rightTab;
  const openCount = threads.filter((t) => t.status === 'open').length + suggestions.length;

  const leftPanel = (
    <section aria-label="Project files" className="flex min-h-0 flex-col bg-surface" style={isMobile ? { flex: 1 } : { width: prefs.leftWidth }}>
      <div className="flex border-b border-line">
        {([['files', Files, 'Files'], ['outline', ListTree, 'Outline'], ['search', Search, 'Search']] as const).map(([id, I, label]) => (
          <button key={id} className={`tab flex flex-1 items-center justify-center gap-1 px-1 py-1.5 text-xs ${prefs.leftTab === id ? 'tab-active' : ''}`} onClick={() => setPrefs({ leftTab: id })}><I size={13} /> {label}</button>
        ))}
      </div>
      <div className="min-h-0 flex-1">
        {prefs.leftTab === 'files' && <FileTree manuscript={manuscript} files={files} activeFileId={activeId} canWrite={canWrite} onOpen={(f) => void openFile(f)} onChanged={() => { loadManuscript(); loadIndex(); }} />}
        {prefs.leftTab === 'outline' && <OutlinePanel fileId={activeFile?.file_kind === 'text' ? activeFile.id : null} fileName={activeFile?.path ?? ''} version={saveStatus?.lastSavedAt ? Date.parse(saveStatus.lastSavedAt) : 0} onGoto={(line) => { if (isMobile) setMobilePane('editor'); window.setTimeout(() => editorRef.current?.gotoLine(line), 50); }} beforeExport={ensureSaved} />}
        {prefs.leftTab === 'search' && <SearchPanel files={files} focusKey={searchFocus} onOpen={(f, line) => void openFile(f, line)} />}
      </div>
    </section>
  );

  const editorPanel = (
    <section aria-label="Editor" className="flex min-h-0 min-w-0 flex-1 flex-col bg-surface">
      <div className="flex h-8 shrink-0 items-center gap-2 border-b border-line px-2 text-xs text-muted">
        <FileCode2 size={13} />
        <span className="truncate font-mono">{activeFile?.path ?? 'No file open'}</span>
        {activeFile?.path === manuscript.main_file_path && <span className="chip">main</span>}
        {saveStatus?.state === 'unsaved' && canWrite && (
          <button className="ml-auto inline-flex items-center gap-1 text-muted hover:text-ink" onClick={() => editorRef.current?.discardChanges()} title="Discard unsaved changes">
            <RotateCcw size={12} /> Cancel changes
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1">
        {!activeFile && <p className="p-6 text-sm text-muted">Choose a file from the tree.</p>}
        {activeFile?.file_kind === 'text' && (
          <TextFileEditor
            key={activeFile.id}
            ref={editorRef}
            file={activeFile}
            canWrite={canWrite}
            autosave={prefs.autosave}
            completion={completion}
            marks={marks}
            onStatus={setSaveStatus}
            onTextChange={onTextChange}
            onMarkClick={(id) => { setFocusReview(id); setPrefs({ rightTab: 'review', rightCollapsed: false }); if (isMobile) setMobilePane('review'); }}
            onSelectionChange={(empty) => setHasSelection(!empty)}
            commands={editorCommands}
          />
        )}
        {activeFile?.file_kind === 'binary' && (
          <AssetPreview key={activeFile.id} file={activeFile} onDownload={() => downloadFile(`/manuscript-files/${activeFile.id}/raw`, activeFile.path.split('/').pop() || 'file').catch(onError)} />
        )}
      </div>
    </section>
  );

  const rightPanel = (
    <section aria-label="Document tools and review" className="flex min-h-0 flex-col bg-surface" style={isMobile ? { flex: 1 } : prefs.view === 'panel' ? { flex: 1 } : { width: Math.min(prefs.rightWidth, Math.max(280, (window.innerWidth - (showLeft ? prefs.leftWidth : 0)) * 0.45)) }}>
      {!isMobile && (
        <div className="flex border-b border-line">
          {([['tools', Wrench, 'Tools'], ['review', MessageSquare, `Review${openCount ? ` (${openCount})` : ''}`], ['history', History, 'History']] as const).map(([id, I, label]) => (
            <button key={id} className={`tab flex items-center gap-1 px-3 py-1.5 text-xs ${rightTab === id ? 'tab-active' : ''}`} onClick={() => setPrefs({ rightTab: id })}><I size={13} /> {label}</button>
          ))}
        </div>
      )}
      <div className="min-h-0 flex-1">
        {rightTab === 'tools' && <DocumentTools manuscript={manuscript} files={files} canWrite={canWrite} busy={toolBusy} report={depsReport} onAction={(a) => void runTool(a)} onSetting={updateSetting} />}
        {rightTab === 'review' && (
          <ReviewPanel manuscriptId={manuscriptId} files={files} activeFileId={activeId} threads={threads} suggestions={suggestions} canComment={canComment} canWrite={canWrite} isOwner={role === 'owner'} focusId={focusReview}
            onJump={jumpToReview} onChanged={() => { loadReview(); void editorRef.current?.reloadIfClean(); }} reviewStatus={manuscript.review_status}
            onReviewStatus={(s) => api.patch<Manuscript>(`/manuscripts/${manuscriptId}`, { review_status: s }).then((m) => setManuscript((cur) => (cur ? { ...cur, review_status: m.review_status } : cur))).catch(onError)} />
        )}
        {rightTab === 'history' && (
          <HistoryPanel file={activeFile} canWrite={canWrite} refreshKey={historyKey} onSaveVersion={() => void saveVersion()}
            beforeRestore={ensureSaved} onRestored={() => void editorRef.current?.reloadIfClean()} />
        )}
      </div>
    </section>
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-11 shrink-0 items-center gap-1.5 overflow-x-auto border-b border-line bg-surface px-2">
        <a href={href({ name: 'project', projectId: manuscript.project_id, tab: 'papers' })}
          onClick={async (e) => { e.preventDefault(); if (await leaveFile()) navigate({ name: 'project', projectId: manuscript.project_id, tab: 'papers' }); }}
          className="icon-btn" aria-label="Back to project"><ArrowLeft size={16} /></a>
        <div className="min-w-0">
          <TitleEditor manuscript={manuscript} canWrite={canWrite} onRenamed={(title) => setManuscript({ ...manuscript, title })} />
          <span className="block truncate text-[11px] text-faint">{manuscript.project_title}</span>
        </div>
        <StatusMenu manuscript={manuscript} canWrite={canWrite} isOwner={role === 'owner'} onChanged={(s) => setManuscript({ ...manuscript, status: s as Manuscript['status'] })} />
        {activeFile?.file_kind === 'text' && <SaveIndicator status={saveStatus} canWrite={canWrite} />}
        <span className="flex-1" />
        {canWrite && activeFile?.file_kind === 'text' && (
          <button className="btn-ghost" onClick={() => void saveNow()} disabled={saveStatus?.state === 'saved' || saveStatus?.state === 'saving'} title="Save (Ctrl+S)">
            <Save size={15} /><span className="hidden lg:inline">Save</span>
          </button>
        )}
        {canWrite && <InsertMenu onPick={setDialog} />}
        {canComment && (
          <button className="btn-ghost" onClick={startComment} disabled={!hasSelection || activeFile?.file_kind !== 'text'} title="Comment on selection (Ctrl+Alt+M)"><MessageSquarePlus size={15} /><span className="hidden lg:inline">Comment</span></button>
        )}
        {canComment && (
          <button className="btn-ghost" onClick={startSuggest} disabled={!hasSelection} title="Propose a change to the selection for an editor to accept"><Pencil size={15} /><span className="hidden lg:inline">Suggest edit</span></button>
        )}
        <button className="btn-primary" onClick={() => void runTool('zip')} disabled={toolBusy === 'zip'} title="Download the complete LaTeX source as a .zip">
          {toolBusy === 'zip' ? <Spinner size={14} /> : <Download size={14} />} <span className="hidden sm:inline">LaTeX project</span>
        </button>
        {!isMobile && (
          <div className="ml-1 flex rounded-md border border-line">
            <button className={`icon-btn rounded-none ${prefs.view === 'editor' ? 'bg-raised text-ink' : ''}`} onClick={() => setPrefs({ view: 'editor' })} aria-label="Editor only" title="Editor only"><PanelLeft size={15} /></button>
            <button className={`icon-btn rounded-none ${prefs.view === 'split' ? 'bg-raised text-ink' : ''}`} onClick={() => setPrefs({ view: 'split', rightCollapsed: false })} aria-label="Editor and tools" title="Editor and tools"><Columns2 size={15} /></button>
            <button className={`icon-btn rounded-none ${prefs.view === 'panel' ? 'bg-raised text-ink' : ''}`} onClick={() => setPrefs({ view: 'panel', rightCollapsed: false })} aria-label="Tools only" title="Tools and review only"><PanelRight size={15} /></button>
          </div>
        )}
        <button className="icon-btn" onClick={() => setPaletteOpen(true)} aria-label="Command palette" title="Command palette (Ctrl+K)"><Command size={15} /></button>
        <button className="icon-btn hidden sm:inline-flex" onClick={() => setHelpOpen(true)} aria-label="Keyboard shortcuts"><Keyboard size={15} /></button>
      </div>

      <div className="flex min-h-0 flex-1">
        {showLeft && leftPanel}
        {!isMobile && showLeft && <ResizeHandle label="Resize file panel" onDrag={(dx) => setPrefs({ leftWidth: Math.min(480, Math.max(160, prefs.leftWidth + dx)) })} />}
        {!isMobile && !showLeft && prefs.view !== 'panel' && (
          <button className="flex w-6 shrink-0 items-start justify-center border-r border-line bg-surface pt-2 text-muted hover:text-ink" onClick={() => setPrefs({ leftCollapsed: false })} aria-label="Show file panel"><BookOpen size={14} /></button>
        )}
        {showEditor && editorPanel}
        {!isMobile && showRight && prefs.view === 'split' && <ResizeHandle label="Resize tools panel" onDrag={(dx) => setPrefs({ rightWidth: Math.min(window.innerWidth * 0.6, Math.max(260, prefs.rightWidth - dx)) })} />}
        {showRight && rightPanel}
      </div>
      {!isMobile && (
        <div className="flex h-6 shrink-0 items-center gap-3 border-t border-line bg-surface px-2 text-[11px] text-faint">
          <button className="hover:text-ink" onClick={() => setPrefs({ leftCollapsed: !prefs.leftCollapsed })}>{prefs.leftCollapsed ? 'Show' : 'Hide'} files</button>
          <button className="hover:text-ink" onClick={() => setPrefs({ rightCollapsed: !prefs.rightCollapsed })}>{prefs.rightCollapsed ? 'Show' : 'Hide'} tools</button>
          {canWrite && (
            <label className="flex cursor-pointer items-center gap-1 hover:text-ink">
              <input type="checkbox" checked={prefs.autosave} onChange={(e) => setPrefs({ autosave: e.target.checked })} className="h-3 w-3" /> Autosave
            </label>
          )}
          {saveStatus?.lastSavedAt && <span>Last saved {timeAgo(saveStatus.lastSavedAt)}</span>}
          <span className="ml-auto">Role: {role}</span>
        </div>
      )}
      {isMobile && (
        <nav className="flex shrink-0 border-t border-line bg-surface" aria-label="Workspace panels">
          {([['files', Files, 'Files'], ['editor', FileCode2, 'Editor'], ['tools', Wrench, 'Tools'], ['review', MessageSquare, 'Review']] as const).map(([id, I, label]) => (
            <button key={id} className={`flex flex-1 flex-col items-center gap-0.5 py-1.5 text-[11px] ${mobilePane === id ? 'text-accent' : 'text-muted'}`} onClick={() => setMobilePane(id)} aria-current={mobilePane === id ? 'page' : undefined}><I size={17} />{label}</button>
          ))}
        </nav>
      )}

      <InsertDialog kind={dialog} onClose={() => setDialog(null)} onInsert={insert} files={files} index={index} manuscriptId={manuscriptId} onFilesChanged={() => { loadManuscript(); loadIndex(); }} />
      <CommentDialog open={Boolean(commentDraft)} quoted={commentDraft?.text ?? ''} onClose={() => setCommentDraft(null)}
        onSubmit={async (body) => {
          if (!commentDraft || !activeFile) return;
          try {
            await ensureSaved();
            await api.post(`/manuscripts/${manuscriptId}/comments`, { file_id: activeFile.id, body, quoted_text: commentDraft.text.slice(0, 2000), anchor: anchorFor(commentDraft) });
            loadReview();
            setPrefs({ rightTab: 'review', rightCollapsed: false });
          } catch (e) {
            onError(e);
            throw e;
          }
        }} />
      <SuggestDialog open={Boolean(suggestDraft)} original={suggestDraft?.text ?? ''} onClose={() => setSuggestDraft(null)}
        onSubmit={async (proposed, note) => {
          if (!suggestDraft || !activeFile) return;
          try {
            await ensureSaved();
            await api.post(`/manuscripts/${manuscriptId}/suggestions`, { file_id: activeFile.id, anchor: anchorFor(suggestDraft), original_text: suggestDraft.text, proposed_text: proposed, note });
            toast('Suggestion sent for review', 'success');
            loadReview();
            setPrefs({ rightTab: 'review', rightCollapsed: false });
          } catch (e) {
            onError(e);
            throw e;
          }
        }} />
      <CommandPalette open={paletteOpen} items={paletteItems} onClose={() => setPaletteOpen(false)} />
      <Modal open={helpOpen} onClose={() => setHelpOpen(false)} title="Keyboard shortcuts">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          {SHORTCUTS.map(([k, v]) => <div key={k} className="contents"><dt><kbd className="kbd text-[11px]">{k}</kbd></dt><dd className="text-muted">{v}</dd></div>)}
        </dl>
        <p className="mt-3 text-xs text-faint">Type \ in the editor for commands and snippets (figure, table, equation, align…). Inside \cite{'{'}, \ref{'{'} or \includegraphics{'{'} you get keys, labels and files.</p>
      </Modal>
    </div>
  );
}

function TitleEditor({ manuscript, canWrite, onRenamed }: { manuscript: Manuscript; canWrite: boolean; onRenamed(t: string): void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(manuscript.title);
  const onError = useErrorToast();
  if (!editing) {
    return <button className={`block max-w-[30vw] truncate text-left text-[13px] font-semibold ${canWrite ? 'hover:text-accent' : 'cursor-default'}`} onClick={() => canWrite && setEditing(true)} title={canWrite ? 'Rename paper' : manuscript.title}>{manuscript.title}</button>;
  }
  const save = () => {
    setEditing(false);
    if (value.trim().length >= 2 && value !== manuscript.title) {
      api.patch(`/manuscripts/${manuscript.id}`, { title: value.trim() }).then(() => onRenamed(value.trim())).catch(onError);
    }
  };
  return <input autoFocus className="input py-0.5 text-[13px] font-semibold" value={value} onChange={(e) => setValue(e.target.value)} onBlur={save} onKeyDown={(e) => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setEditing(false); }} aria-label="Paper title" />;
}

function StatusMenu({ manuscript, canWrite, isOwner, onChanged }: { manuscript: Manuscript; canWrite: boolean; isOwner: boolean; onChanged(s: string): void }) {
  const [open, setOpen] = useState(false);
  const onError = useErrorToast();
  if (!canWrite) return <span className="hidden sm:inline"><StatusBadge status={manuscript.status} /></span>;
  return (
    <Dropdown open={open} setOpen={setOpen} trigger={<button className="hidden items-center gap-0.5 sm:inline-flex" onClick={() => setOpen(!open)} aria-label="Paper status"><StatusBadge status={manuscript.status} /><ChevronDown size={12} className="text-faint" /></button>}>
      {MANUSCRIPT_STATUSES.map((s) => {
        const locked = OWNER_ONLY_STATUSES.has(s) && !isOwner;
        return (
          <button key={s} className="menu-item" disabled={locked} title={locked ? 'Only the project owner can set publication outcomes' : ''}
            onClick={() => api.patch(`/manuscripts/${manuscript.id}/status`, { status: s }).then(() => onChanged(s)).catch(onError)}>
            <StatusBadge status={s} /> {locked && <Lock size={12} className="ml-auto text-faint" />}
          </button>
        );
      })}
    </Dropdown>
  );
}

function InsertMenu({ onPick }: { onPick(k: InsertKind): void }) {
  const [open, setOpen] = useState(false);
  return (
    <Dropdown open={open} setOpen={setOpen} align="right" trigger={<button className="btn-ghost" onClick={() => setOpen(!open)}><Wand2 size={15} /><span className="hidden lg:inline">Insert</span><ChevronDown size={12} /></button>}>
      <button className="menu-item" onClick={() => onPick('figure')}><ImageIcon size={14} /> Figure…</button>
      <button className="menu-item" onClick={() => onPick('table')}><Table2 size={14} /> Table…</button>
      <button className="menu-item" onClick={() => onPick('equation')}><Sigma size={14} /> Equation…</button>
      <button className="menu-item" onClick={() => onPick('cite')}><Quote size={14} /> Citation…</button>
    </Dropdown>
  );
}
