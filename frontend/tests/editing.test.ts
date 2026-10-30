import { describe, expect, it } from 'vitest';
import { locateAnchor } from '../src/lib/anchors';
import { lintLatex } from '../src/editor/latexLint';

describe('comment anchors survive later edits', () => {
  const quoted = '\\section{Methods}';
  const original = 'intro\n\\section{Methods}\nbody';
  const anchor = { from: 6, to: 6 + quoted.length, line: 2, context_before: 'intro\n', context_after: '\nbody' };

  it('uses stored offsets while they still match', () => {
    expect(locateAnchor(original, anchor, quoted)).toEqual({ from: 6, to: 6 + quoted.length });
  });
  it('re-finds the quote after text was inserted before it', () => {
    const shifted = '% new preamble line\n' + original;
    const span = locateAnchor(shifted, anchor, quoted)!;
    expect(shifted.slice(span.from, span.to)).toBe(quoted);
  });
  it('gives up rather than guessing when the quote is ambiguous or gone', () => {
    expect(locateAnchor('\\section{Methods}\n\\section{Methods}', { ...anchor, from: 99, to: 120, context_before: '', context_after: '' }, quoted)).toBeNull();
    expect(locateAnchor('nothing here', anchor, quoted)).toBeNull();
  });
});

describe('LaTeX structure check', () => {
  it('accepts balanced source', () => {
    expect(lintLatex('\\begin{document}\n\\section{A} {x} 100\\% \\{ % } comment\n\\end{document}')).toEqual([]);
  });
  it('flags unclosed and mismatched environments', () => {
    const issues = lintLatex('\\begin{figure}\n\\begin{center}\n\\end{figure}');
    expect(issues.map((i) => i.message)).toContain('\\end{figure} closes \\begin{center}.');
    expect(issues.some((i) => i.message.includes('never closed'))).toBe(true);
  });
  it('flags unbalanced braces but ignores verbatim blocks', () => {
    expect(lintLatex('\\textbf{bold').some((i) => i.message.includes('never closed'))).toBe(true);
    expect(lintLatex('\\begin{verbatim}\n{ unbalanced\n\\end{verbatim}')).toEqual([]);
  });
});
