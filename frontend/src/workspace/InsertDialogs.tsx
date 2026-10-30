import { useMemo, useRef, useState } from 'react';
import katex from 'katex';
import { Minus, Plus, Upload } from 'lucide-react';
import { api } from '../services/apiClient';
import { escapeLatex, parseDelimited, tableToLatex } from '../lib/text';
import type { CitationIndex, ManuscriptFile } from '../types';
import { Modal, Spinner, useErrorToast } from '../components/ui';

export type InsertKind = 'figure' | 'table' | 'equation' | 'cite' | null;

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40);
}

function Preview({ code }: { code: string }) {
  return (
    <div>
      <span className="label">LaTeX that will be inserted at the cursor</span>
      <pre className="max-h-48 overflow-auto rounded-md border border-line bg-raised p-2 font-mono text-xs">{code}</pre>
    </div>
  );
}

export function InsertDialog({ kind, onClose, onInsert, files, index, manuscriptId, onFilesChanged }: { kind: InsertKind; onClose(): void; onInsert(text: string): void; files: ManuscriptFile[]; index: CitationIndex | null; manuscriptId: string; onFilesChanged(): void }) {
  if (kind === 'figure') return <FigureDialog onClose={onClose} onInsert={onInsert} files={files} manuscriptId={manuscriptId} onFilesChanged={onFilesChanged} />;
  if (kind === 'table') return <TableDialog onClose={onClose} onInsert={onInsert} />;
  if (kind === 'equation') return <EquationDialog onClose={onClose} onInsert={onInsert} />;
  if (kind === 'cite') return <CiteDialog onClose={onClose} onInsert={onInsert} index={index} />;
  return null;
}

function Footer({ onClose, onInsert, disabled }: { onClose(): void; onInsert(): void; disabled?: boolean }) {
  return <><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={disabled} onClick={onInsert}>Insert</button></>;
}

function FigureDialog({ onClose, onInsert, files, manuscriptId, onFilesChanged }: { onClose(): void; onInsert(t: string): void; files: ManuscriptFile[]; manuscriptId: string; onFilesChanged(): void }) {
  const images = files.filter((f) => f.file_kind === 'binary' && /\.(png|jpe?g|pdf|eps)$/i.test(f.path));
  const [path, setPath] = useState(images[0]?.path ?? '');
  const [caption, setCaption] = useState('');
  const [label, setLabel] = useState('');
  const [width, setWidth] = useState('0.8');
  const [uploading, setUploading] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const onError = useErrorToast();
  const effectiveLabel = label || `fig:${slug(path.split('/').pop()?.replace(/\.[^.]+$/, '') ?? 'figure')}`;
  const code = [
    '\\begin{figure}[htbp]',
    '  \\centering',
    `  \\includegraphics[width=${width}\\linewidth]{${path}}`,
    `  \\caption{${caption ? escapeLatex(caption) : 'Caption'}}`,
    `  \\label{${effectiveLabel}}`,
    '\\end{figure}',
  ].join('\n');
  const upload = async (f: File) => {
    setUploading(true);
    const form = new FormData();
    form.append('files', f);
    form.append('folder', 'figures');
    try {
      const res = await api.form<{ files: { path: string }[] }>(`/manuscripts/${manuscriptId}/files/upload`, form);
      setPath(res.files[0].path);
      onFilesChanged();
    } catch (e) {
      onError(e);
    } finally {
      setUploading(false);
    }
  };
  return (
    <Modal open onClose={onClose} title="Insert figure" footer={<Footer onClose={onClose} disabled={!path} onInsert={() => onInsert(code + '\n')} />}>
      <div className="space-y-3">
        <div className="flex items-end gap-2">
          <label className="block flex-1"><span className="label">Image</span>
            <select className="input" value={path} onChange={(e) => setPath(e.target.value)}>
              {images.length === 0 && <option value="">No images yet: upload one</option>}
              {images.map((f) => <option key={f.id} value={f.path}>{f.path}</option>)}
            </select>
          </label>
          <input ref={input} type="file" hidden accept=".png,.jpg,.jpeg,.pdf,.eps" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          <button className="btn-outline" onClick={() => input.current?.click()} disabled={uploading}>{uploading ? <Spinner size={14} /> : <Upload size={14} />} Upload</button>
        </div>
        <label className="block"><span className="label">Caption</span><input className="input" value={caption} onChange={(e) => setCaption(e.target.value)} /></label>
        <div className="grid grid-cols-2 gap-2">
          <label className="block"><span className="label">Label</span><input className="input font-mono" placeholder={effectiveLabel} value={label} onChange={(e) => setLabel(e.target.value)} /></label>
          <label className="block"><span className="label">Width (× line width)</span><input className="input" value={width} onChange={(e) => setWidth(e.target.value.replace(/[^0-9.]/g, ''))} /></label>
        </div>
        <Preview code={code} />
      </div>
    </Modal>
  );
}

function TableDialog({ onClose, onInsert }: { onClose(): void; onInsert(t: string): void }) {
  const [rows, setRows] = useState<string[][]>([['Method', 'Metric A', 'Metric B'], ['', '', ''], ['', '', '']]);
  const [caption, setCaption] = useState('');
  const [label, setLabel] = useState('tab:results');
  const [header, setHeader] = useState(true);
  const [paste, setPaste] = useState('');
  const code = useMemo(() => tableToLatex(rows, caption, label, header), [rows, caption, label, header]);
  const cols = Math.max(...rows.map((r) => r.length));
  const setCell = (r: number, c: number, v: string) => setRows((all) => all.map((row, i) => (i === r ? Array.from({ length: cols }, (_, j) => (j === c ? v : row[j] ?? '')) : row)));
  return (
    <Modal wide open onClose={onClose} title="Insert table" footer={<Footer onClose={onClose} onInsert={() => onInsert(code + '\n')} />}>
      <div className="space-y-3">
        <div className="overflow-x-auto">
          <table className="border-collapse">
            <tbody>
              {rows.map((row, r) => (
                <tr key={r}>
                  {Array.from({ length: cols }, (_, c) => (
                    <td key={c} className="p-0.5"><input className={`input w-32 py-1 text-xs ${header && r === 0 ? 'font-semibold' : ''}`} value={row[c] ?? ''} onChange={(e) => setCell(r, c, e.target.value)} aria-label={`Row ${r + 1} column ${c + 1}`} /></td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap gap-1 text-xs">
          <button className="btn-ghost px-2 py-1" onClick={() => setRows((a) => [...a, Array(cols).fill('')])}><Plus size={12} /> Row</button>
          <button className="btn-ghost px-2 py-1" disabled={rows.length <= 1} onClick={() => setRows((a) => a.slice(0, -1))}><Minus size={12} /> Row</button>
          <button className="btn-ghost px-2 py-1" onClick={() => setRows((a) => a.map((r) => [...r, '']))}><Plus size={12} /> Column</button>
          <button className="btn-ghost px-2 py-1" disabled={cols <= 1} onClick={() => setRows((a) => a.map((r) => r.slice(0, cols - 1)))}><Minus size={12} /> Column</button>
          <label className="ml-2 flex items-center gap-1"><input type="checkbox" checked={header} onChange={(e) => setHeader(e.target.checked)} /> First row is a header</label>
        </div>
        <label className="block"><span className="label">Or paste CSV / spreadsheet cells</span>
          <textarea className="input min-h-[60px] font-mono text-xs" value={paste} onChange={(e) => { setPaste(e.target.value); const parsed = parseDelimited(e.target.value); if (parsed.length) setRows(parsed); }} placeholder={'Method,RMSE\nBaseline,0.52'} />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="block"><span className="label">Caption</span><input className="input" value={caption} onChange={(e) => setCaption(e.target.value)} /></label>
          <label className="block"><span className="label">Label</span><input className="input font-mono" value={label} onChange={(e) => setLabel(e.target.value)} /></label>
        </div>
        <Preview code={code} />
        <p className="text-[11px] text-faint">Uses booktabs (\toprule, \midrule): add \usepackage{'{'}booktabs{'}'} if your preamble lacks it.</p>
      </div>
    </Modal>
  );
}

function EquationDialog({ onClose, onInsert }: { onClose(): void; onInsert(t: string): void }) {
  const [math, setMath] = useState('\\frac{\\partial u}{\\partial t} + (u \\cdot \\nabla) u = -\\nabla p + \\nu \\Delta u');
  const [env, setEnv] = useState<'equation' | 'align' | 'inline'>('equation');
  const [label, setLabel] = useState('eq:');
  const rendered = useMemo(() => {
    try {
      return { html: katex.renderToString(env === 'align' ? `\\begin{aligned}${math}\\end{aligned}` : math, { displayMode: env !== 'inline', throwOnError: true, trust: false, strict: 'ignore' }), error: null };
    } catch (e) {
      return { html: '', error: (e as Error).message };
    }
  }, [math, env]);
  const labelLine = label && label !== 'eq:' ? `\n  \\label{${label}}` : '';
  const code = env === 'inline' ? `$${math}$` : `\\begin{${env}}\n  ${math}${labelLine}\n\\end{${env}}`;
  return (
    <Modal wide open onClose={onClose} title="Insert equation" footer={<Footer onClose={onClose} disabled={!math.trim()} onInsert={() => onInsert(env === 'inline' ? code : code + '\n')} />}>
      <div className="space-y-3">
        <div className="flex gap-2">
          {(['equation', 'align', 'inline'] as const).map((e) => <button key={e} className={`btn-outline ${env === e ? 'border-accent text-accent' : ''}`} onClick={() => setEnv(e)}>{e === 'inline' ? 'Inline $…$' : e}</button>)}
        </div>
        <textarea className="input min-h-[90px] font-mono text-xs" value={math} onChange={(e) => setMath(e.target.value)} spellCheck={false} aria-label="Math source" />
        <div className="min-h-[60px] overflow-x-auto rounded-md border border-line bg-white p-3 text-black">
          {rendered.error ? <p className="text-xs text-red-600">Preview: {rendered.error}</p> : <div dangerouslySetInnerHTML={{ __html: rendered.html }} />}
        </div>
        <p className="text-[11px] text-faint">Preview uses KaTeX and may differ slightly from how TeX typesets it. Your source is inserted exactly as written.</p>
        {env !== 'inline' && <label className="block"><span className="label">Label</span><input className="input font-mono" value={label} onChange={(e) => setLabel(e.target.value)} /></label>}
        <Preview code={code} />
      </div>
    </Modal>
  );
}

function CiteDialog({ onClose, onInsert, index }: { onClose(): void; onInsert(t: string): void; index: CitationIndex | null }) {
  const [q, setQ] = useState('');
  const [picked, setPicked] = useState<string[]>([]);
  const [cmd, setCmd] = useState('cite');
  const list = (index?.citations ?? []).filter((c) => !q || `${c.key} ${c.title} ${c.authors} ${c.year}`.toLowerCase().includes(q.toLowerCase())).slice(0, 100);
  const code = `\\${cmd}{${picked.join(', ')}}`;
  return (
    <Modal wide open onClose={onClose} title="Insert citation" footer={<Footer onClose={onClose} disabled={!picked.length} onInsert={() => onInsert(code)} />}>
      <div className="space-y-2">
        <div className="flex gap-2">
          <input className="input" placeholder="Search key, title, author, year" value={q} onChange={(e) => setQ(e.target.value)} />
          <select className="input w-auto" value={cmd} onChange={(e) => setCmd(e.target.value)}><option>cite</option><option>citep</option><option>citet</option><option>parencite</option><option>textcite</option></select>
        </div>
        {list.length === 0 && <p className="text-sm text-muted">No references found. Add them in the project's References tab or a .bib file.</p>}
        <div className="max-h-72 divide-y divide-line overflow-y-auto rounded-md border border-line">
          {list.map((c) => (
            <label key={c.key} className="flex cursor-pointer items-start gap-2 px-2 py-1.5 text-sm hover:bg-raised">
              <input type="checkbox" className="mt-1" checked={picked.includes(c.key)} onChange={(e) => setPicked((p) => (e.target.checked ? [...p, c.key] : p.filter((k) => k !== c.key)))} />
              <span className="min-w-0"><code className="text-xs">{c.key}</code> <span className="text-muted">{c.title}</span><span className="block text-xs text-faint">{c.authors} {c.year} · {c.source}</span></span>
            </label>
          ))}
        </div>
        {picked.length > 0 && <Preview code={code} />}
        {picked.some((k) => index?.citations.find((c) => c.key === k)?.source === 'library') && (
          <p className="text-[11px] text-faint">Some keys exist only in the project library. Use “Add project references to the .bib” in the Tools panel so the exported source resolves them.</p>
        )}
      </div>
    </Modal>
  );
}

export function CommentDialog({ open, quoted, onClose, onSubmit }: { open: boolean; quoted: string; onClose(): void; onSubmit(body: string): Promise<void> }) {
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  return (
    <Modal open={open} onClose={onClose} title="Comment"
      footer={<><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={busy || !body.trim()} onClick={async () => { setBusy(true); try { await onSubmit(body); setBody(''); onClose(); } finally { setBusy(false); } }}>{busy && <Spinner size={14} />} Comment</button></>}>
      {quoted && <p className="mb-2 max-h-24 overflow-auto border-l-2 border-warn pl-2 font-mono text-xs text-muted">{quoted}</p>}
      <textarea autoFocus className="input min-h-[90px]" placeholder="Write a comment. Use @username to mention a collaborator." value={body} onChange={(e) => setBody(e.target.value)} />
    </Modal>
  );
}

export function SuggestDialog({ open, original, onClose, onSubmit }: { open: boolean; original: string; onClose(): void; onSubmit(proposed: string, note: string): Promise<void> }) {
  const [proposed, setProposed] = useState(original);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [openedWith, setOpenedWith] = useState<string | null>(null);
  if (open && openedWith !== original) {
    setOpenedWith(original);
    setProposed(original);
    setNote('');
  }
  return (
    <Modal wide open={open} onClose={onClose} title="Suggest an edit"
      footer={<><button className="btn-ghost" onClick={onClose}>Cancel</button><button className="btn-primary" disabled={busy || proposed === original} onClick={async () => { setBusy(true); try { await onSubmit(proposed, note); onClose(); } finally { setBusy(false); } }}>{busy && <Spinner size={14} />} Suggest</button></>}>
      <div className="space-y-2">
        <span className="label">Current text</span>
        <pre className="max-h-32 overflow-auto rounded-md bg-danger/5 p-2 font-mono text-xs line-through decoration-danger/50">{original || '(empty: suggests an insertion)'}</pre>
        <label className="block"><span className="label">Proposed text</span><textarea className="input min-h-[100px] font-mono text-xs" value={proposed} onChange={(e) => setProposed(e.target.value)} spellCheck={false} /></label>
        <label className="block"><span className="label">Note (optional)</span><input className="input" value={note} onChange={(e) => setNote(e.target.value)} /></label>
        <p className="text-[11px] text-faint">The document is not changed until an editor accepts the suggestion.</p>
      </div>
    </Modal>
  );
}
