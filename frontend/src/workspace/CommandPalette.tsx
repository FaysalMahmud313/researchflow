import { useEffect, useMemo, useRef, useState } from 'react';
import { FileText, Zap } from 'lucide-react';

export interface PaletteItem {
  id: string;
  label: string;
  hint?: string;
  kind: 'file' | 'action';
  run(): void;
}

function score(label: string, q: string): number {
  if (!q) return 1;
  const l = label.toLowerCase();
  const s = q.toLowerCase();
  if (l.includes(s)) return 100 - l.indexOf(s);
  let i = 0;
  for (const ch of l) if (ch === s[i]) i++;
  return i === s.length ? 10 : 0;
}

export function CommandPalette({ open, items, onClose }: { open: boolean; items: PaletteItem[]; onClose(): void }) {
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (open) {
      setQ('');
      setActive(0);
      setTimeout(() => input.current?.focus(), 0);
    }
  }, [open]);
  const filtered = useMemo(() => items.map((it) => ({ it, s: score(it.label, q) })).filter((x) => x.s > 0).sort((a, b) => b.s - a.s).slice(0, 40).map((x) => x.it), [items, q]);
  if (!open) return null;
  const run = (it?: PaletteItem) => {
    if (!it) return;
    onClose();
    it.run();
  };
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 p-4 pt-[12vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="card w-full max-w-lg overflow-hidden shadow-pop" role="dialog" aria-label="Command palette">
        <input
          ref={input}
          className="w-full border-b border-line bg-surface px-3 py-2.5 text-sm outline-none"
          placeholder="Go to file or run a command…"
          value={q}
          onChange={(e) => { setQ(e.target.value); setActive(0); }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') onClose();
            else if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, filtered.length - 1)); }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
            else if (e.key === 'Enter') run(filtered[active]);
          }}
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-list"
        />
        <ul id="palette-list" role="listbox" className="max-h-80 overflow-y-auto p-1">
          {filtered.length === 0 && <li className="px-3 py-2 text-sm text-muted">No matches.</li>}
          {filtered.map((it, i) => (
            <li key={it.id} role="option" aria-selected={i === active}>
              <button className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] ${i === active ? 'bg-accent/10' : ''}`} onMouseEnter={() => setActive(i)} onClick={() => run(it)}>
                {it.kind === 'file' ? <FileText size={14} className="text-muted" /> : <Zap size={14} className="text-muted" />}
                <span className="flex-1 truncate">{it.label}</span>
                {it.hint && <kbd className="kbd">{it.hint}</kbd>}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
