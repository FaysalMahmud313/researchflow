import { useEffect, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import { api } from '../services/apiClient';
import type { ManuscriptFile } from '../types';
import { Spinner } from '../components/ui';

interface Hit { file: ManuscriptFile; line: number; text: string }

/** Search across every text file of the paper (current server state, including collaborators' edits). */
export function SearchPanel({ files, focusKey, onOpen }: { files: ManuscriptFile[]; focusKey: number; onOpen(file: ManuscriptFile, line: number): void }) {
  const [q, setQ] = useState('');
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), [focusKey]);

  const run = async () => {
    const term = q.trim();
    if (!term) return;
    setBusy(true);
    const textFiles = files.filter((f) => f.file_kind === 'text');
    const results: Hit[] = [];
    await Promise.all(
      textFiles.map(async (f) => {
        try {
          const full = await api.get<{ content: string }>(`/manuscript-files/${f.id}`);
          full.content.split('\n').forEach((line, i) => {
            const hay = caseSensitive ? line : line.toLowerCase();
            if (hay.includes(caseSensitive ? term : term.toLowerCase())) results.push({ file: f, line: i + 1, text: line.trim().slice(0, 160) });
          });
        } catch {
          /* skip unreadable file */
        }
      }),
    );
    results.sort((a, b) => a.file.path.localeCompare(b.file.path) || a.line - b.line);
    setHits(results.slice(0, 500));
    setBusy(false);
  };

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-line p-2">
        <div className="relative">
          <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-faint" />
          <input ref={input} className="input pl-7 text-xs" placeholder="Search all files (Enter)" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && run()} aria-label="Search in paper" />
        </div>
        <label className="mt-1 flex items-center gap-1 text-[11px] text-muted"><input type="checkbox" checked={caseSensitive} onChange={(e) => setCaseSensitive(e.target.checked)} /> Match case</label>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {busy && <div className="p-2"><Spinner size={14} /></div>}
        {hits && !busy && <p className="px-2 py-1 text-[11px] text-faint">{hits.length} match{hits.length === 1 ? '' : 'es'}</p>}
        {hits?.map((h, i) => (
          <button key={i} className="block w-full px-2 py-1 text-left hover:bg-raised" onClick={() => onOpen(h.file, h.line)}>
            <span className="block text-[11px] text-faint">{h.file.path}:{h.line}</span>
            <span className="block truncate font-mono text-[11px]">{h.text}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
