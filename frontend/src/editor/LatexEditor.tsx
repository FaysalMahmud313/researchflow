import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import { EditorState, Compartment, StateEffect, StateField, type Extension } from '@codemirror/state';
import {
  EditorView,
  Decoration,
  type DecorationSet,
  keymap,
  lineNumbers,
  highlightActiveLine,
  highlightActiveLineGutter,
  drawSelection,
  dropCursor,
  rectangularSelection,
  crosshairCursor,
  highlightSpecialChars,
} from '@codemirror/view';
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
import { bracketMatching, foldGutter, foldKeymap, indentOnInput, indentUnit } from '@codemirror/language';
import { closeBrackets, closeBracketsKeymap, completionKeymap } from '@codemirror/autocomplete';
import { highlightSelectionMatches, search, searchKeymap } from '@codemirror/search';
import { linter, lintGutter, lintKeymap } from '@codemirror/lint';
import { latexCompletion, latexFolding, latexHighlight, latexLanguage, type CompletionData } from './latexSupport';
import { lintLatex } from './latexLint';

export interface EditorMark {
  id: string;
  from: number;
  to: number;
  kind: 'comment' | 'suggestion';
  title?: string;
}

export interface LatexEditorHandle {
  focus(): void;
  gotoLine(line: number): void;
  select(from: number, to: number): void;
  insertAtCursor(text: string): void;
  selection(): { from: number; to: number; text: string; line: number };
  /** Replace the whole document (e.g. after loading a newer saved version). Clears undo history. */
  setContent(text: string): void;
  getContent(): string;
}

interface Props {
  initialContent: string;
  readOnly: boolean;
  language: 'latex' | 'plain';
  completion: CompletionData;
  marks: EditorMark[];
  onChange(text: string): void;
  onMarkClick?: (id: string) => void;
  onSelectionChange?: (empty: boolean) => void;
  commands: {
    save(): void;
    saveVersion(): void;
    togglePanel(): void;
    palette(): void;
    comment(): void;
  };
}

const setMarks = StateEffect.define<EditorMark[]>();
const marksField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(deco, tr) {
    deco = deco.map(tr.changes);
    for (const e of tr.effects) {
      if (e.is(setMarks)) {
        const len = tr.state.doc.length;
        const ranges = e.value
          .filter((m) => m.from >= 0 && m.to <= len && m.to > m.from)
          .sort((a, b) => a.from - b.from)
          .map((m) =>
            Decoration.mark({
              class: m.kind === 'comment' ? 'rf-comment-mark' : 'rf-suggest-mark',
              attributes: { 'data-mark-id': m.id, title: m.title ?? '' },
            }).range(m.from, m.to),
          );
        deco = Decoration.set(ranges, true);
      }
    }
    return deco;
  },
  provide: (f) => EditorView.decorations.from(f),
});

const editorTheme = EditorView.theme({
  '&': { backgroundColor: 'rgb(var(--surface))', color: 'rgb(var(--ink))' },
  '.cm-content': { caretColor: 'rgb(var(--accent))', padding: '8px 0' },
  '.cm-gutters': { backgroundColor: 'rgb(var(--surface))', color: 'rgb(var(--faint))', borderRight: '1px solid rgb(var(--line))' },
  '.cm-activeLine': { backgroundColor: 'rgb(var(--raised) / 0.6)' },
  '.cm-activeLineGutter': { backgroundColor: 'rgb(var(--raised))', color: 'rgb(var(--ink))' },
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection': { backgroundColor: 'rgb(var(--accent) / 0.22) !important' },
  '.cm-cursor': { borderLeftColor: 'rgb(var(--accent))', borderLeftWidth: '2px' },
  '.cm-tooltip': { backgroundColor: 'rgb(var(--surface))', border: '1px solid rgb(var(--line))', borderRadius: '8px', overflow: 'hidden' },
  '.cm-tooltip-autocomplete > ul > li[aria-selected]': { backgroundColor: 'rgb(var(--accent) / 0.15)', color: 'rgb(var(--ink))' },
  '.cm-completionDetail': { color: 'rgb(var(--faint))', marginLeft: '8px', fontStyle: 'normal' },
  '.cm-panels': { backgroundColor: 'rgb(var(--raised))', color: 'rgb(var(--ink))', borderColor: 'rgb(var(--line))' },
  '.cm-panel.cm-search input, .cm-panel.cm-search button': { fontSize: '12px' },
  '.cm-textfield': { backgroundColor: 'rgb(var(--surface))', border: '1px solid rgb(var(--line))', borderRadius: '4px', color: 'rgb(var(--ink))' },
  '.cm-button': { backgroundImage: 'none', backgroundColor: 'rgb(var(--surface))', border: '1px solid rgb(var(--line))', borderRadius: '4px', color: 'rgb(var(--ink))' },
  '.cm-foldPlaceholder': { backgroundColor: 'rgb(var(--raised))', border: '1px solid rgb(var(--line))', color: 'rgb(var(--muted))' },
  '.cm-searchMatch': { backgroundColor: 'rgb(var(--warn) / 0.25)' },
  '.cm-searchMatch-selected': { backgroundColor: 'rgb(var(--warn) / 0.5)' },
});

const latexLinter = linter((view) =>
  lintLatex(view.state.doc.toString()).map((i) => ({ from: i.from, to: i.to, severity: 'warning' as const, message: i.message, source: 'LaTeX check' })),
  { delay: 600 },
);

export const LatexEditor = forwardRef<LatexEditorHandle, Props>(function LatexEditor(props, ref) {
  const host = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const readOnlyComp = useRef(new Compartment());
  const propsRef = useRef(props);
  propsRef.current = props;
  const extensionsRef = useRef<Extension[]>([]);

  useEffect(() => {
    if (!host.current) return;
    const cmds = () => propsRef.current.commands;
    const appKeys = keymap.of([
      { key: 'Mod-s', run: () => (cmds().save(), true), preventDefault: true },
      { key: 'Mod-Shift-s', run: () => (cmds().saveVersion(), true), preventDefault: true },
      { key: 'Mod-\\', run: () => (cmds().togglePanel(), true) },
      { key: 'Mod-k', run: () => (cmds().palette(), true), preventDefault: true },
      { key: 'Mod-Alt-m', run: () => (cmds().comment(), true) },
    ]);
    const isLatex = props.language === 'latex';
    const extensions: Extension[] = [
      appKeys,
      lineNumbers(),
      highlightActiveLineGutter(),
      highlightSpecialChars(),
      history(),
      foldGutter(),
      drawSelection(),
      dropCursor(),
      EditorState.allowMultipleSelections.of(true),
      indentOnInput(),
      indentUnit.of('  '),
      bracketMatching(),
      closeBrackets(),
      rectangularSelection(),
      crosshairCursor(),
      highlightActiveLine(),
      highlightSelectionMatches(),
      search({ top: true }),
      EditorView.lineWrapping,
      isLatex ? [latexLanguage, latexHighlight, latexFolding, latexCompletion(props.completion), lintGutter(), latexLinter] : [],
      keymap.of([...closeBracketsKeymap, ...defaultKeymap, ...historyKeymap, ...searchKeymap, ...foldKeymap, ...completionKeymap, ...lintKeymap, indentWithTab]),
      readOnlyComp.current.of([EditorState.readOnly.of(props.readOnly)]),
      marksField,
      editorTheme,
      EditorView.contentAttributes.of({ 'aria-label': 'LaTeX source editor', spellcheck: 'true' }),
      EditorView.updateListener.of((u) => {
        if (u.docChanged) propsRef.current.onChange(u.state.doc.toString());
        if (u.selectionSet) propsRef.current.onSelectionChange?.(u.state.selection.main.empty);
      }),
      EditorView.domEventHandlers({
        click: (e) => {
          const target = (e.target as HTMLElement).closest('[data-mark-id]');
          if (target) propsRef.current.onMarkClick?.(target.getAttribute('data-mark-id') || '');
          return false;
        },
      }),
    ];
    extensionsRef.current = extensions;
    const view = new EditorView({ parent: host.current, state: EditorState.create({ doc: props.initialContent, extensions }) });
    viewRef.current = view;
    return () => {
      view.destroy();
      viewRef.current = null;
    };
    // The parent remounts the editor per file; content updates go through setContent().
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    viewRef.current?.dispatch({ effects: readOnlyComp.current.reconfigure([EditorState.readOnly.of(props.readOnly)]) });
  }, [props.readOnly]);

  useEffect(() => {
    viewRef.current?.dispatch({ effects: setMarks.of(props.marks) });
  }, [props.marks]);

  useImperativeHandle(ref, () => ({
    focus: () => viewRef.current?.focus(),
    getContent: () => viewRef.current?.state.doc.toString() ?? '',
    setContent(text: string) {
      const view = viewRef.current;
      if (!view) return;
      // A fresh state resets undo history, so "undo" cannot resurrect content from before a reload.
      view.setState(EditorState.create({ doc: text, extensions: extensionsRef.current }));
      view.dispatch({ effects: [readOnlyComp.current.reconfigure([EditorState.readOnly.of(propsRef.current.readOnly)]), setMarks.of(propsRef.current.marks)] });
    },
    gotoLine(line: number) {
      const view = viewRef.current;
      if (!view) return;
      const l = view.state.doc.line(Math.max(1, Math.min(line, view.state.doc.lines)));
      view.dispatch({ selection: { anchor: l.from }, effects: EditorView.scrollIntoView(l.from, { y: 'center' }) });
      view.focus();
    },
    select(from: number, to: number) {
      const view = viewRef.current;
      if (!view) return;
      const len = view.state.doc.length;
      const a = Math.min(Math.max(0, from), len);
      const b = Math.min(Math.max(0, to), len);
      view.dispatch({ selection: { anchor: a, head: b }, effects: EditorView.scrollIntoView(a, { y: 'center' }) });
      view.focus();
    },
    insertAtCursor(text: string) {
      const view = viewRef.current;
      if (!view || view.state.readOnly) return;
      const sel = view.state.selection.main;
      view.dispatch({ changes: { from: sel.from, to: sel.to, insert: text }, selection: { anchor: sel.from + text.length } });
      view.focus();
    },
    selection() {
      const view = viewRef.current;
      if (!view) return { from: 0, to: 0, text: '', line: 1 };
      const sel = view.state.selection.main;
      return { from: sel.from, to: sel.to, text: view.state.sliceDoc(sel.from, sel.to), line: view.state.doc.lineAt(sel.from).number };
    },
  }));

  return <div ref={host} className="h-full min-h-0 overflow-hidden" />;
});
