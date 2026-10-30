import { useState } from 'react';
import { AlertTriangle, BookMarked, CheckCircle2, ClipboardCopy, FileArchive, FileCode2, FileDown, Images, ListTree, SearchCheck } from 'lucide-react';
import type { Manuscript, ManuscriptFile } from '../types';
import { Spinner } from '../components/ui';

export type ToolAction =
  | 'zip' | 'flat' | 'file' | 'bib' | 'assets' | 'copy-selection' | 'save-selection' | 'section' | 'deps' | 'sync-bib';

export interface DependencyReport {
  missing_inputs: { path: string; from: string; line: number }[];
  missing_figures: { path: string; from: string; line: number }[];
  missing_bibliographies: { path: string; from: string; line: number }[];
  undefined_citations: string[];
  undefined_references: string[];
  warnings: string[];
}

interface Props {
  manuscript: Manuscript;
  files: ManuscriptFile[];
  canWrite: boolean;
  busy: ToolAction | null;
  report: DependencyReport | null;
  onAction(action: ToolAction): void;
  onSetting(patch: { main_file_path?: string; compiler?: string }): void;
}

function Row({ icon, label, detail, onClick, busy }: { icon: JSX.Element; label: string; detail?: string; onClick(): void; busy?: boolean }) {
  return (
    <button className="flex w-full items-start gap-2.5 rounded-md px-2 py-2 text-left hover:bg-raised" onClick={onClick} disabled={busy}>
      <span className="mt-0.5 text-muted">{busy ? <Spinner size={15} /> : icon}</span>
      <span className="min-w-0">
        <span className="block text-[13px] font-medium text-ink">{label}</span>
        {detail && <span className="block text-xs text-muted">{detail}</span>}
      </span>
    </button>
  );
}

export function DocumentTools({ manuscript, files, canWrite, busy, report, onAction, onSetting }: Props) {
  const [showChecks, setShowChecks] = useState(false);
  const texFiles = files.filter((f) => f.file_kind === 'text' && f.path.endsWith('.tex'));
  const problems = report
    ? report.missing_inputs.length + report.missing_figures.length + report.missing_bibliographies.length + report.undefined_citations.length + report.undefined_references.length
    : 0;

  return (
    <div className="h-full overflow-y-auto p-3 text-sm">
      <p className="mb-3 rounded-lg border border-line bg-raised/60 px-3 py-2 text-xs text-muted">
        ResearchFlow writes and exports <b className="text-ink">LaTeX source</b>; it does not compile PDFs. Download the project and build it
        with your own TeX installation (for example <code className="font-mono">latexmk -pdf {manuscript.main_file_path}</code>) or an online LaTeX editor.
      </p>

      <h3 className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wide text-faint">Download</h3>
      <Row icon={<FileArchive size={16} />} label="Download LaTeX project (.zip)" detail="All source files, bibliography and figures with their folders, plus a README" busy={busy === 'zip'} onClick={() => onAction('zip')} />
      <Row icon={<FileCode2 size={16} />} label="Full paper as one .tex" detail="Included files inlined into a single source file" busy={busy === 'flat'} onClick={() => onAction('flat')} />
      <Row icon={<FileDown size={16} />} label="Current file" busy={busy === 'file'} onClick={() => onAction('file')} />
      <Row icon={<BookMarked size={16} />} label="Bibliography (.bib)" busy={busy === 'bib'} onClick={() => onAction('bib')} />
      <Row icon={<Images size={16} />} label="Figures & assets (.zip)" busy={busy === 'assets'} onClick={() => onAction('assets')} />

      <h3 className="mb-1 mt-4 px-2 text-[11px] font-semibold uppercase tracking-wide text-faint">Sections & selections</h3>
      <Row icon={<ListTree size={16} />} label="Copy or download a section" detail="Abstract, introduction, results… from the Outline" onClick={() => onAction('section')} />
      <Row icon={<ClipboardCopy size={16} />} label="Copy selection as LaTeX" detail="Paragraphs, equations, tables or figures you selected" onClick={() => onAction('copy-selection')} />
      <Row icon={<FileDown size={16} />} label="Download selection (.tex)" onClick={() => onAction('save-selection')} />

      <h3 className="mb-1 mt-4 px-2 text-[11px] font-semibold uppercase tracking-wide text-faint">Checks</h3>
      <Row icon={<SearchCheck size={16} />} label="Check missing files & citations" detail="\input files, figures, .bib files, cite keys and \ref labels" busy={busy === 'deps'}
        onClick={() => { setShowChecks(true); onAction('deps'); }} />
      {showChecks && report && (
        <div className="mx-2 mb-2 space-y-1.5 rounded-md border border-line p-2 text-xs">
          {problems === 0 && report.warnings.length === 0 ? (
            <p className="flex items-center gap-1.5 text-success"><CheckCircle2 size={14} /> Nothing missing. Files, figures, citations and labels all resolve.</p>
          ) : (
            <>
              {[...report.missing_inputs, ...report.missing_figures, ...report.missing_bibliographies].map((m, i) => (
                <p key={i} className="flex gap-1.5"><AlertTriangle size={13} className="mt-0.5 shrink-0 text-warn" /><span>Missing <code>{m.path}</code> in {m.from}{m.line ? `:${m.line}` : ''}</span></p>
              ))}
              {report.undefined_citations.length > 0 && <p><b>Cite keys not in any .bib:</b> {report.undefined_citations.join(', ')}</p>}
              {report.undefined_references.length > 0 && <p><b>\ref without \label:</b> {report.undefined_references.join(', ')}</p>}
              {report.warnings.map((w) => <p key={w} className="text-warn">{w}</p>)}
            </>
          )}
        </div>
      )}

      {canWrite && (
        <>
          <Row icon={<BookMarked size={16} />} label="Add project references to the .bib" detail="Appends library entries this paper's .bib file doesn't have yet" busy={busy === 'sync-bib'} onClick={() => onAction('sync-bib')} />
          <h3 className="mb-1 mt-4 px-2 text-[11px] font-semibold uppercase tracking-wide text-faint">Paper settings</h3>
          <label className="block px-2 py-1">
            <span className="label">Main file</span>
            <select className="input" value={manuscript.main_file_path} onChange={(e) => onSetting({ main_file_path: e.target.value })}>
              {texFiles.map((f) => <option key={f.id} value={f.path}>{f.path}</option>)}
            </select>
          </label>
          <label className="block px-2 py-1">
            <span className="label">TeX engine (used in the README instructions)</span>
            <select className="input" value={manuscript.compiler} onChange={(e) => onSetting({ compiler: e.target.value })}>
              <option value="pdflatex">pdfLaTeX</option>
              <option value="xelatex">XeLaTeX</option>
              <option value="lualatex">LuaLaTeX</option>
            </select>
          </label>
        </>
      )}
    </div>
  );
}
