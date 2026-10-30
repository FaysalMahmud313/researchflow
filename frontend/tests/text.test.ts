import { describe, expect, it } from 'vitest';
import { codePointToUtf16, escapeLatex, parseDelimited, tableToLatex, utf16ToCodePoint } from '../src/lib/text';
import { href, parseRoute } from '../src/lib/app';

describe('offset conversion between the editor (UTF-16) and the server (code points)', () => {
  const text = 'a😀b𝔽c';
  it('maps indices after astral characters', () => {
    // 'a'=1 unit, '😀'=2 units, 'b'=1, '𝔽'=2, 'c'=1
    expect(utf16ToCodePoint(text, 3)).toBe(2); // before 'b'
    expect(utf16ToCodePoint(text, 6)).toBe(4); // before 'c'
    expect(codePointToUtf16(text, 2)).toBe(3);
    expect(codePointToUtf16(text, 4)).toBe(6);
  });
  it('round-trips every boundary', () => {
    for (let cp = 0; cp <= [...text].length; cp++) {
      expect(utf16ToCodePoint(text, codePointToUtf16(text, cp))).toBe(cp);
    }
  });
  it('is the identity for BMP-only text', () => {
    expect(utf16ToCodePoint('Résumé ∂u/∂t', 8)).toBe(8);
  });
});

describe('LaTeX generation helpers', () => {
  it('escapes LaTeX special characters', () => {
    expect(escapeLatex('100% of $5 & a_b #1 {x} ~ ^ \\')).toBe('100\\% of \\$5 \\& a\\_b \\#1 \\{x\\} \\textasciitilde{} \\textasciicircum{} \\textbackslash{}');
  });
  it('parses spreadsheet TSV and quoted CSV', () => {
    expect(parseDelimited('A\tB\n1\t2\n')).toEqual([['A', 'B'], ['1', '2']]);
    expect(parseDelimited('name,note\n"Smith, J.","said ""hi"""')).toEqual([['name', 'note'], ['Smith, J.', 'said "hi"']]);
  });
  it('builds a booktabs table with a header rule and escaped cells', () => {
    const tex = tableToLatex([['Method', 'Error %'], ['Ours', '1.2']], 'Results', 'tab:r', true);
    expect(tex).toContain('\\begin{tabular}{ll}');
    expect(tex).toContain('Method & Error \\% \\\\\n    \\midrule');
    expect(tex).toContain('\\label{tab:r}');
    expect(tex.trim().endsWith('\\end{table}')).toBe(true);
  });
});

describe('routing', () => {
  it('round-trips workspace and project routes', () => {
    const r = { name: 'workspace' as const, manuscriptId: 'doc_1', fileId: 'mf_2' };
    expect(parseRoute(href(r))).toEqual(r);
    expect(parseRoute('#/p/prj_9/references')).toEqual({ name: 'project', projectId: 'prj_9', tab: 'references' });
    expect(parseRoute('#/unknown')).toEqual({ name: 'section', section: 'overview' });
    expect(parseRoute('#/papers')).toEqual({ name: 'section', section: 'papers' });
  });
});
