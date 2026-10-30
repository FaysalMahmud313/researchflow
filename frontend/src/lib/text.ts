/**
 * The editor (CodeMirror) indexes text in UTF-16 code units; the server indexes in Unicode
 * code points. They differ for astral characters (emoji, 𝔽, 𝒜 …), so offsets crossing the API
 * boundary are converted explicitly.
 */
export function utf16ToCodePoint(text: string, index: number): number {
  let cp = 0;
  for (let i = 0; i < index && i < text.length; i++) {
    const c = text.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff && i + 1 < text.length) i++;
    cp++;
  }
  return cp;
}

export function codePointToUtf16(text: string, cpIndex: number): number {
  let i = 0;
  let cp = 0;
  while (cp < cpIndex && i < text.length) {
    const c = text.charCodeAt(i);
    i += c >= 0xd800 && c <= 0xdbff ? 2 : 1;
    cp++;
  }
  return i;
}

export function formatBytes(n: number): string {
  if (!Number.isFinite(n)) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = n;
  let u = 0;
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024;
    u++;
  }
  return `${v < 10 && u > 0 ? v.toFixed(1) : Math.round(v)} ${units[u]}`;
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '';
  const t = new Date(iso.split('#')[0]).getTime();
  if (Number.isNaN(t)) return '';
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 45) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.round(s / 86400)} d ago`;
  return new Date(t).toLocaleDateString();
}

export function initials(name: string): string {
  return name
    .replace(/^(Dr|Prof)\.?\s+/i, '')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('');
}

/** Escape text for inclusion in LaTeX source (table cells, captions entered in dialogs). */
export function escapeLatex(s: string): string {
  return s.replace(/[\\{}$&#^_%~]/g, (ch) => {
    switch (ch) {
      case '\\': return '\\textbackslash{}';
      case '~': return '\\textasciitilde{}';
      case '^': return '\\textasciicircum{}';
      default: return '\\' + ch;
    }
  });
}

/** Parse pasted CSV/TSV (spreadsheet copy) into rows. Handles quoted cells. */
export function parseDelimited(input: string): string[][] {
  const text = input.replace(/\r\n?/g, '\n').replace(/\n+$/, '');
  if (!text) return [];
  const delimiter = text.includes('\t') ? '\t' : ',';
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"' && cell === '') quoted = true;
    else if (ch === delimiter) {
      row.push(cell);
      cell = '';
    } else if (ch === '\n') {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
    } else cell += ch;
  }
  row.push(cell);
  rows.push(row);
  return rows;
}

export function tableToLatex(rows: string[][], caption: string, label: string, header: boolean): string {
  const cols = Math.max(1, ...rows.map((r) => r.length));
  const body = rows.map((r, i) => {
    const cells = Array.from({ length: cols }, (_, c) => escapeLatex((r[c] ?? '').trim()));
    const line = `    ${cells.join(' & ')} \\\\`;
    return header && i === 0 ? `${line}\n    \\midrule` : line;
  });
  return [
    '\\begin{table}[htbp]',
    '  \\centering',
    caption ? `  \\caption{${escapeLatex(caption)}}` : '',
    label ? `  \\label{${label}}` : '',
    `  \\begin{tabular}{${'l'.repeat(cols)}}`,
    '    \\toprule',
    ...body,
    '    \\bottomrule',
    '  \\end{tabular}',
    '\\end{table}',
  ].filter(Boolean).join('\n');
}
