import { StreamLanguage, HighlightStyle, syntaxHighlighting, foldService } from '@codemirror/language';
import { stex } from '@codemirror/legacy-modes/mode/stex';
import { tags as t } from '@lezer/highlight';
import {
  autocompletion,
  snippetCompletion,
  type Completion,
  type CompletionContext,
  type CompletionResult,
} from '@codemirror/autocomplete';
import type { Extension } from '@codemirror/state';
import type { CitationIndex } from '../types';

export const latexLanguage = StreamLanguage.define(stex);

const v = (name: string) => `rgb(var(--${name}))`;

export const latexHighlight = syntaxHighlighting(
  HighlightStyle.define([
    { tag: [t.tagName, t.keyword], color: v('accent'), fontWeight: '500' },
    { tag: [t.atom, t.typeName], color: '#0e9f6e' },
    { tag: t.comment, color: v('faint'), fontStyle: 'italic' },
    { tag: [t.string, t.special(t.string)], color: '#c2410c' },
    { tag: [t.number], color: '#b45309' },
    { tag: [t.bracket], color: v('muted') },
    { tag: [t.variableName, t.special(t.variableName)], color: '#7c3aed' },
    { tag: t.heading, fontWeight: '700' },
    { tag: t.invalid, color: v('danger') },
  ]),
);

/** Fold \begin{env}…\end{env} blocks and sectioning commands up to the next heading of the same or higher level. */
const LEVELS: Record<string, number> = { part: 0, chapter: 1, section: 2, subsection: 3, subsubsection: 4, paragraph: 5 };
export const latexFolding = foldService.of((state, lineStart, lineEnd) => {
  const text = state.doc.sliceString(lineStart, lineEnd);
  const begin = /\\begin\{([^}]+)\}/.exec(text);
  if (begin && !text.includes(`\\end{${begin[1]}}`)) {
    const env = begin[1];
    let depth = 0;
    for (let n = state.doc.lineAt(lineStart).number; n <= state.doc.lines; n++) {
      const line = state.doc.line(n);
      depth += (line.text.match(new RegExp(`\\\\begin\\{${env.replace(/[*]/g, '\\*')}\\}`, 'g')) || []).length;
      depth -= (line.text.match(new RegExp(`\\\\end\\{${env.replace(/[*]/g, '\\*')}\\}`, 'g')) || []).length;
      if (depth <= 0 && n > state.doc.lineAt(lineStart).number) {
        const prev = state.doc.line(n - 1);
        return prev.to > lineEnd ? { from: lineEnd, to: prev.to } : null;
      }
    }
    return null;
  }
  const head = /^\s*\\(part|chapter|section|subsection|subsubsection|paragraph)\*?[[{]/.exec(text);
  if (head) {
    const level = LEVELS[head[1]];
    const startNo = state.doc.lineAt(lineStart).number;
    let endPos = state.doc.length;
    for (let n = startNo + 1; n <= state.doc.lines; n++) {
      const line = state.doc.line(n);
      const m = /^\s*\\(part|chapter|section|subsection|subsubsection|paragraph)\*?[[{]/.exec(line.text);
      if ((m && LEVELS[m[1]] <= level) || /^\s*\\(end\{document\}|bibliography\{|printbibliography|appendix)/.test(line.text)) {
        endPos = state.doc.line(n - 1).to;
        break;
      }
    }
    return endPos > lineEnd ? { from: lineEnd, to: endPos } : null;
  }
  return null;
});

const COMMANDS: [string, string][] = [
  ['section', 'Section heading'], ['subsection', 'Subsection'], ['subsubsection', 'Sub-subsection'], ['paragraph', 'Paragraph heading'],
  ['chapter', 'Chapter'], ['label', 'Label for cross-references'], ['ref', 'Reference to a label'], ['eqref', 'Equation reference'],
  ['cref', 'Clever reference'], ['autoref', 'Automatic reference'], ['cite', 'Citation'], ['citep', 'Parenthetical citation'],
  ['citet', 'Textual citation'], ['textbf', 'Bold'], ['textit', 'Italic'], ['emph', 'Emphasis'], ['texttt', 'Monospace'],
  ['underline', 'Underline'], ['footnote', 'Footnote'], ['url', 'URL'], ['href', 'Hyperlink'], ['includegraphics', 'Insert image'],
  ['caption', 'Caption'], ['centering', 'Center content'], ['input', 'Include a .tex file'], ['include', 'Include a chapter'],
  ['usepackage', 'Load a package'], ['documentclass', 'Document class'], ['maketitle', 'Typeset title'], ['tableofcontents', 'Contents'],
  ['bibliography', 'Bibliography file'], ['bibliographystyle', 'Bibliography style'], ['printbibliography', 'Print bibliography'],
  ['newcommand', 'Define a command'], ['renewcommand', 'Redefine a command'], ['frac', 'Fraction'], ['sqrt', 'Square root'],
  ['sum', 'Summation'], ['int', 'Integral'], ['prod', 'Product'], ['lim', 'Limit'], ['infty', 'Infinity'], ['partial', 'Partial derivative'],
  ['nabla', 'Nabla'], ['mathbb', 'Blackboard bold'], ['mathcal', 'Calligraphic'], ['mathbf', 'Bold math'], ['mathrm', 'Upright math'],
  ['left', 'Left delimiter'], ['right', 'Right delimiter'], ['alpha', 'α'], ['beta', 'β'], ['gamma', 'γ'], ['delta', 'δ'],
  ['epsilon', 'ε'], ['theta', 'θ'], ['lambda', 'λ'], ['mu', 'μ'], ['sigma', 'σ'], ['phi', 'φ'], ['omega', 'ω'], ['cdot', '·'],
  ['times', '×'], ['leq', '≤'], ['geq', '≥'], ['neq', '≠'], ['approx', '≈'], ['in', '∈'], ['rightarrow', '→'], ['hline', 'Table rule'],
  ['toprule', 'Booktabs top rule'], ['midrule', 'Booktabs mid rule'], ['bottomrule', 'Booktabs bottom rule'], ['item', 'List item'],
  ['newpage', 'Page break'], ['clearpage', 'Flush floats and break'], ['appendix', 'Start appendix'], ['today', 'Current date'],
];

const ENVIRONMENTS = ['equation', 'equation*', 'align', 'align*', 'gather', 'figure', 'figure*', 'table', 'table*', 'tabular',
  'itemize', 'enumerate', 'description', 'abstract', 'quote', 'verbatim', 'center', 'minipage', 'algorithm', 'algorithmic',
  'theorem', 'lemma', 'proof', 'definition', 'cases', 'matrix', 'pmatrix', 'bmatrix', 'thebibliography'];

export const SNIPPETS: { label: string; detail: string; template: string }[] = [
  { label: 'figure', detail: 'Figure with caption and label', template: '\\begin{figure}[htbp]\n\t\\centering\n\t\\includegraphics[width=0.8\\linewidth]{${path}}\n\t\\caption{${Caption}}\n\t\\label{fig:${label}}\n\\end{figure}\n${}' },
  { label: 'table', detail: 'Booktabs table', template: '\\begin{table}[htbp]\n\t\\centering\n\t\\caption{${Caption}}\n\t\\label{tab:${label}}\n\t\\begin{tabular}{lll}\n\t\t\\toprule\n\t\t${A} & B & C \\\\\n\t\t\\midrule\n\t\t1 & 2 & 3 \\\\\n\t\t\\bottomrule\n\t\\end{tabular}\n\\end{table}\n${}' },
  { label: 'equation', detail: 'Numbered equation', template: '\\begin{equation}\n\t${E = mc^2}\n\t\\label{eq:${label}}\n\\end{equation}\n${}' },
  { label: 'align', detail: 'Aligned equations', template: '\\begin{align}\n\t${a} &= ${b} \\\\\n\t&= ${c}\n\\end{align}\n${}' },
  { label: 'itemize', detail: 'Bulleted list', template: '\\begin{itemize}\n\t\\item ${}\n\\end{itemize}' },
  { label: 'enumerate', detail: 'Numbered list', template: '\\begin{enumerate}\n\t\\item ${}\n\\end{enumerate}' },
  { label: 'section', detail: 'Section with label', template: '\\section{${Title}}\n\\label{sec:${label}}\n${}' },
  { label: 'subsection', detail: 'Subsection with label', template: '\\subsection{${Title}}\n\\label{sec:${label}}\n${}' },
  { label: 'algorithm', detail: 'Algorithm (algorithm + algpseudocode)', template: '\\begin{algorithm}[htbp]\n\t\\caption{${Name}}\n\t\\label{alg:${label}}\n\t\\begin{algorithmic}[1]\n\t\t\\State ${}\n\t\\end{algorithmic}\n\\end{algorithm}' },
  { label: 'theorem', detail: 'Theorem environment', template: '\\begin{theorem}\n\t${}\n\\end{theorem}' },
  { label: 'proof', detail: 'Proof environment', template: '\\begin{proof}\n\t${}\n\\end{proof}' },
  { label: 'cases', detail: 'Piecewise definition', template: '\\begin{cases}\n\t${a} & \\text{if } ${x > 0} \\\\\n\t${b} & \\text{otherwise}\n\\end{cases}' },
  { label: 'matrix', detail: 'Bracketed matrix', template: '\\begin{bmatrix}\n\t${a} & ${b} \\\\\n\t${c} & ${d}\n\\end{bmatrix}' },
];

export interface CompletionData {
  index: CitationIndex | null;
}

function commandSource(ctx: CompletionContext): CompletionResult | null {
  const word = ctx.matchBefore(/\\[A-Za-z]*$/);
  if (!word || (word.from === word.to && !ctx.explicit)) return null;
  const options: Completion[] = [
    ...COMMANDS.map(([name, info]) => ({ label: `\\${name}`, type: 'keyword', detail: info, boost: name.startsWith('sec') ? 2 : 0 })),
    ...SNIPPETS.map((s) => snippetCompletion(s.template, { label: `\\${s.label}`, detail: s.detail, type: 'text', boost: 1 })),
  ];
  return { from: word.from, options, validFor: /^\\[A-Za-z]*$/ };
}

function argumentSource(data: CompletionData) {
  return (ctx: CompletionContext): CompletionResult | null => {
    const before = ctx.state.sliceDoc(Math.max(0, ctx.pos - 200), ctx.pos);
    const m = /\\([A-Za-z]+)\*?(?:\[[^\]]*\]){0,2}\{([^{}]*)$/.exec(before);
    if (!m) return null;
    const cmd = m[1];
    const arg = m[2];
    const lastComma = arg.lastIndexOf(',');
    const from = ctx.pos - (arg.length - (lastComma + 1)) + (arg.slice(lastComma + 1).match(/^\s*/)?.[0].length ?? 0);
    const index = data.index;
    if (/cite|parencite|textcite|autocite/.test(cmd)) {
      const items = index?.citations ?? [];
      return {
        from,
        options: items.map((c) => ({
          label: c.key,
          detail: `${c.year ?? ''}`,
          info: `${c.title || ''}\n${c.authors || ''}${c.source && c.source !== 'library' ? `\n(${c.source})` : ''}`,
          type: 'constant',
        })),
        validFor: /^[^,}\s]*$/,
      };
    }
    if (/^(ref|eqref|autoref|cref|Cref|pageref|nameref|vref)$/.test(cmd)) {
      return {
        from,
        options: (index?.labels ?? []).map((l) => ({ label: l.label, detail: `${l.file}:${l.line}`, type: 'variable' })),
        validFor: /^[^,}\s]*$/,
      };
    }
    if (cmd === 'begin' || cmd === 'end') {
      return { from, options: ENVIRONMENTS.map((e) => ({ label: e, type: 'type' })), validFor: /^[A-Za-z*]*$/ };
    }
    if (cmd === 'input' || cmd === 'include' || cmd === 'subfile') {
      return {
        from,
        options: (index?.files ?? []).filter((f) => f.path.endsWith('.tex')).map((f) => ({ label: f.path.replace(/\.tex$/, ''), type: 'text' })),
      };
    }
    if (cmd === 'includegraphics') {
      return {
        from,
        options: (index?.files ?? []).filter((f) => /\.(png|jpe?g|pdf|eps)$/i.test(f.path)).map((f) => ({ label: f.path, type: 'text' })),
      };
    }
    if (cmd === 'bibliography' || cmd === 'addbibresource') {
      return {
        from,
        options: (index?.files ?? []).filter((f) => f.path.endsWith('.bib')).map((f) => ({ label: cmd === 'bibliography' ? f.path.replace(/\.bib$/, '') : f.path, type: 'text' })),
      };
    }
    return null;
  };
}

export function latexCompletion(data: CompletionData): Extension {
  return autocompletion({ override: [argumentSource(data), commandSource], activateOnTyping: true, maxRenderedOptions: 60 });
}
