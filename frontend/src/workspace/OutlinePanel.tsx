import { useEffect, useState } from 'react';
import { Copy, Download, RefreshCw, Sigma, Image, Table2, AlignLeft } from 'lucide-react';
import { api, ApiError, downloadFile } from '../services/apiClient';
import { useApp } from '../lib/app';
import type { OutlineItem } from '../types';
import { Spinner } from '../components/ui';

interface Props {
  fileId: string | null;
  fileName: string;
  version: number;
  onGoto(line: number): void;
  beforeExport(): Promise<void>;
}

const KIND_ICON: Record<string, JSX.Element> = {
  figure: <Image size={12} />,
  table: <Table2 size={12} />,
  equation: <Sigma size={12} />,
  align: <Sigma size={12} />,
  gather: <Sigma size={12} />,
  multline: <Sigma size={12} />,
  abstract: <AlignLeft size={12} />,
};

export function OutlinePanel({ fileId, fileName, version, onGoto, beforeExport }: Props) {
  const [items, setItems] = useState<OutlineItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { toast } = useApp();

  const load = () => {
    if (!fileId) return;
    setBusy(true);
    api
      .get<{ items: OutlineItem[] }>(`/manuscript-files/${fileId}/outline`)
      .then((r) => {
        setItems(r.items);
        setError(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(false));
  };

  useEffect(() => {
    const t = window.setTimeout(load, version === 0 ? 0 : 1500);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileId, version]);

  const sectionUrl = (it: OutlineItem, download: boolean) => `/manuscript-files/${fileId}/section?start=${it.start}&end=${it.end}${download ? '&download=true' : ''}`;

  const copy = async (it: OutlineItem) => {
    try {
      await beforeExport();
      const text = await api.text(sectionUrl(it, false));
      await navigator.clipboard.writeText(text);
      toast(`Copied “${it.title}” as LaTeX`, 'success');
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) load();
      toast(e instanceof Error ? e.message : 'Copy failed', 'error');
    }
  };

  const download = async (it: OutlineItem) => {
    try {
      await beforeExport();
      await downloadFile(sectionUrl(it, true), `${it.title}.tex`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) load();
      toast(e instanceof Error ? e.message : 'Download failed', 'error');
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center border-b border-line px-2 py-1">
        <span className="mr-auto truncate text-[11px] font-semibold uppercase tracking-wide text-faint">Outline · {fileName}</span>
        <button className="icon-btn" onClick={load} aria-label="Refresh outline">{busy ? <Spinner size={13} /> : <RefreshCw size={13} />}</button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-1">
        {!fileId && <p className="p-2 text-xs text-muted">Open a .tex file to see its outline.</p>}
        {error && <p className="p-2 text-xs text-danger">{error}</p>}
        {items?.length === 0 && <p className="p-2 text-xs text-muted">No sections, figures, tables or equations found.</p>}
        {items?.map((it, i) => (
          <div key={`${it.start}-${i}`} className="group flex items-center gap-1 rounded-md pr-1 text-[13px] hover:bg-raised" style={{ paddingLeft: it.level === 9 ? 18 : 4 + Math.max(0, it.level - 2) * 12 }}>
            <button className="flex min-w-0 flex-1 items-center gap-1.5 py-1 text-left" onClick={() => onGoto(it.line)} title={`Line ${it.line}${it.label ? ` · ${it.label}` : ''}`}>
              {KIND_ICON[it.kind] && <span className="text-faint">{KIND_ICON[it.kind]}</span>}
              <span className={`truncate ${it.level <= 2 ? 'font-medium text-ink' : 'text-muted'}`}>{it.title || it.kind}</span>
            </button>
            <button className="icon-btn h-6 w-6 opacity-0 focus:opacity-100 group-hover:opacity-100" onClick={() => copy(it)} aria-label={`Copy ${it.title} as LaTeX`} title="Copy as LaTeX"><Copy size={12} /></button>
            <button className="icon-btn h-6 w-6 opacity-0 focus:opacity-100 group-hover:opacity-100" onClick={() => download(it)} aria-label={`Download ${it.title} as .tex`} title="Download .tex"><Download size={12} /></button>
          </div>
        ))}
      </div>
    </div>
  );
}
