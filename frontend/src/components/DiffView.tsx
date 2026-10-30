import { useEffect, useRef } from 'react';
import { EditorState, type Extension } from '@codemirror/state';
import { EditorView, lineNumbers } from '@codemirror/view';
import { MergeView, unifiedMergeView } from '@codemirror/merge';
import { syntaxHighlighting, defaultHighlightStyle } from '@codemirror/language';
import { python } from '@codemirror/lang-python';
import { javascript } from '@codemirror/lang-javascript';
import { markdown } from '@codemirror/lang-markdown';
import { latexHighlight, latexLanguage } from '../editor/latexSupport';

export function languageFor(nameOrLang: string): Extension {
  const l = nameOrLang.toLowerCase();
  if (/(^|\.)(py|python|ipynb)$/.test(l) || l === 'python') return python();
  if (/(^|\.)(js|jsx|ts|tsx|javascript|typescript)$/.test(l)) return javascript({ typescript: /ts/.test(l), jsx: /x$/.test(l) });
  if (/(^|\.)(md|markdown)$/.test(l)) return markdown();
  if (/(^|\.)(tex|latex|bib|sty|cls)$/.test(l) || l === 'latex') return [latexLanguage, latexHighlight];
  return [];
}

const theme = EditorView.theme({
  '&': { backgroundColor: 'rgb(var(--surface))', color: 'rgb(var(--ink))', fontSize: '12.5px' },
  '.cm-gutters': { backgroundColor: 'rgb(var(--surface))', color: 'rgb(var(--faint))', borderRight: '1px solid rgb(var(--line))' },
  '.cm-scroller': { fontFamily: 'JetBrains Mono, ui-monospace, Menlo, Consolas, monospace' },
  '.cm-changedLine, &.cm-merge-b .cm-changedLine': { backgroundColor: 'rgb(22 163 74 / 0.12)' },
  '&.cm-merge-a .cm-changedLine, .cm-deletedChunk': { backgroundColor: 'rgb(220 38 38 / 0.12)' },
  '.cm-changedText, &.cm-merge-b .cm-changedText': { background: 'rgb(22 163 74 / 0.3)' },
  '&.cm-merge-a .cm-changedText, .cm-deletedChunk .cm-deletedText': { background: 'rgb(220 38 38 / 0.3)' },
  '.cm-collapsedLines': { backgroundColor: 'rgb(var(--raised))', color: 'rgb(var(--muted))' },
});

interface Props {
  left: string;
  right: string;
  language: string;
  mode: 'split' | 'unified';
  height?: string;
}

export function DiffView({ left, right, language, mode, height = '60vh' }: Props) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current) return;
    const common: Extension[] = [lineNumbers(), EditorView.editable.of(false), EditorState.readOnly.of(true), syntaxHighlighting(defaultHighlightStyle), languageFor(language), theme];
    if (mode === 'split') {
      const view = new MergeView({
        parent: host.current,
        a: { doc: left, extensions: common },
        b: { doc: right, extensions: common },
        collapseUnchanged: { margin: 3, minSize: 6 },
        gutter: true,
      });
      return () => view.destroy();
    }
    const view = new EditorView({
      parent: host.current,
      state: EditorState.create({ doc: right, extensions: [...common, unifiedMergeView({ original: left, mergeControls: false, collapseUnchanged: { margin: 3, minSize: 6 } })] }),
    });
    return () => view.destroy();
  }, [left, right, language, mode]);
  return <div ref={host} className="overflow-auto rounded-md border border-line" style={{ maxHeight: height }} />;
}
