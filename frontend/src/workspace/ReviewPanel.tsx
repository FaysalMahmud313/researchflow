import { useState } from 'react';
import { Check, CornerDownRight, MessageSquare, RotateCcw, Trash2, X } from 'lucide-react';
import { api } from '../services/apiClient';
import { useApp } from '../lib/app';
import { timeAgo } from '../lib/text';
import type { DocComment, ManuscriptFile, Suggestion } from '../types';
import { Avatar, EmptyState, useErrorToast } from '../components/ui';

interface Props {
  manuscriptId: string;
  files: ManuscriptFile[];
  activeFileId: string | null;
  threads: DocComment[];
  suggestions: Suggestion[];
  canComment: boolean;
  canWrite: boolean;
  isOwner: boolean;
  focusId: string | null;
  onJump(fileId: string | null, item: DocComment | Suggestion): void;
  onChanged(): void;
  reviewStatus: string;
  onReviewStatus(status: string): void;
}

export function ReviewPanel(props: Props) {
  const { threads, suggestions, files, activeFileId } = props;
  const [scope, setScope] = useState<'file' | 'all'>('file');
  const [status, setStatus] = useState<'open' | 'resolved'>('open');
  const { user } = useApp();
  const pathOf = (id: string | null) => files.find((f) => f.id === id)?.path ?? 'Whole paper';
  const visibleThreads = threads.filter((t) => t.status === status && (scope === 'all' || t.file_id === activeFileId || !t.file_id));
  const visibleSuggestions = status === 'open' ? suggestions.filter((s) => scope === 'all' || s.file_id === activeFileId) : [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-1 border-b border-line px-2 py-1.5 text-xs">
        <select className="rounded border border-line bg-surface px-1 py-0.5" value={scope} onChange={(e) => setScope(e.target.value as 'file' | 'all')} aria-label="Scope">
          <option value="file">This file</option><option value="all">All files</option>
        </select>
        <select className="rounded border border-line bg-surface px-1 py-0.5" value={status} onChange={(e) => setStatus(e.target.value as 'open' | 'resolved')} aria-label="Status">
          <option value="open">Open</option><option value="resolved">Resolved</option>
        </select>
        <span className="ml-auto" />
        {props.canComment && (
          <select className="rounded border border-line bg-surface px-1 py-0.5" value={props.reviewStatus} onChange={(e) => props.onReviewStatus(e.target.value)} aria-label="Review state" title="Review workflow state (separate from publication status)">
            <option value="draft">Drafting</option>
            <option value="in_review">Ready for review</option>
            <option value="changes_requested">Changes requested</option>
            <option value="approved">Approved</option>
          </select>
        )}
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-2">
        {visibleSuggestions.map((s) => (
          <SuggestionCard key={s.id} s={s} path={pathOf(s.file_id)} focused={props.focusId === s.id} canWrite={props.canWrite} mine={s.author_id === user?.id} onJump={() => props.onJump(s.file_id, s)} onChanged={props.onChanged} />
        ))}
        {visibleThreads.map((t) => (
          <ThreadCard key={t.id} t={t} path={pathOf(t.file_id)} focused={props.focusId === t.id} canComment={props.canComment} canDelete={(id) => id === user?.id || props.isOwner} manuscriptId={props.manuscriptId} onJump={() => props.onJump(t.file_id, t)} onChanged={props.onChanged} />
        ))}
        {visibleThreads.length === 0 && visibleSuggestions.length === 0 && (
          <EmptyState icon={<MessageSquare size={22} />} title={status === 'open' ? 'No open comments' : 'No resolved comments'}>
            {props.canComment && status === 'open' ? 'Select text in the editor and press Comment or Suggest.' : undefined}
          </EmptyState>
        )}
      </div>
    </div>
  );
}

function ThreadCard({ t, path, focused, canComment, canDelete, manuscriptId, onJump, onChanged }: { t: DocComment; path: string; focused: boolean; canComment: boolean; canDelete(authorId: string): boolean; manuscriptId: string; onJump(): void; onChanged(): void }) {
  const [reply, setReply] = useState('');
  const onError = useErrorToast();
  const send = async () => {
    if (!reply.trim()) return;
    try {
      await api.post(`/manuscripts/${manuscriptId}/comments`, { parent_id: t.id, body: reply });
      setReply('');
      onChanged();
    } catch (e) {
      onError(e);
    }
  };
  return (
    <div className={`rounded-lg border p-2 text-[13px] ${focused ? 'border-accent ring-1 ring-accent/30' : 'border-line'} bg-surface`}>
      <button className="mb-1 block w-full text-left" onClick={onJump}>
        <span className="block text-[11px] text-faint">{path}{t.anchor.line ? ` · line ${t.anchor.line}` : ''}</span>
        {t.quoted_text && <span className="mt-0.5 block truncate border-l-2 border-warn pl-2 font-mono text-[11px] text-muted">{t.quoted_text}</span>}
      </button>
      {[t, ...(t.replies ?? [])].map((c) => (
        <div key={c.id} className={`group flex gap-2 ${c.parent_id ? 'mt-2 pl-3' : ''}`}>
          <Avatar name={c.author_name} userId={c.author_id} size={22} />
          <div className="min-w-0 flex-1">
            <p className="text-xs"><b className="font-medium">{c.author_name}</b> <span className="text-faint">{timeAgo(c.created_at)}</span></p>
            <p className="whitespace-pre-wrap break-words">{c.body}</p>
          </div>
          {canDelete(c.author_id) && <button className="icon-btn h-6 w-6 opacity-0 group-hover:opacity-100" onClick={() => api.del(`/doc-comments/${c.id}`).then(onChanged).catch(onError)} aria-label="Delete comment"><Trash2 size={12} /></button>}
        </div>
      ))}
      {t.status === 'resolved' && t.resolved_by_name && <p className="mt-1 text-[11px] text-faint">Resolved by {t.resolved_by_name}</p>}
      {canComment && (
        <div className="mt-2 flex items-center gap-1">
          {t.status === 'open' && (
            <input className="input py-1 text-xs" placeholder="Reply… (@username to mention)" value={reply} onChange={(e) => setReply(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && send()} aria-label="Reply" />
          )}
          {t.status === 'open' && reply && <button className="icon-btn" onClick={send} aria-label="Send reply"><CornerDownRight size={14} /></button>}
          <button className="btn-ghost shrink-0 px-2 py-1 text-xs" onClick={() => api.patch(`/doc-comments/${t.id}`, { status: t.status === 'open' ? 'resolved' : 'open' }).then(onChanged).catch(onError)}>
            {t.status === 'open' ? <><Check size={12} /> Resolve</> : <><RotateCcw size={12} /> Reopen</>}
          </button>
        </div>
      )}
    </div>
  );
}

function SuggestionCard({ s, path, focused, canWrite, mine, onJump, onChanged }: { s: Suggestion; path: string; focused: boolean; canWrite: boolean; mine: boolean; onJump(): void; onChanged(): void }) {
  const onError = useErrorToast();
  const { toast } = useApp();
  const act = async (action: 'accept' | 'reject') => {
    try {
      await api.post(`/doc-suggestions/${s.id}/${action}`);
      toast(action === 'accept' ? 'Suggestion applied' : 'Suggestion rejected', 'success');
    } catch (e) {
      onError(e);
    } finally {
      onChanged();
    }
  };
  return (
    <div className={`rounded-lg border p-2 text-[13px] ${focused ? 'border-accent ring-1 ring-accent/30' : 'border-line'} bg-surface`}>
      <button className="block w-full text-left" onClick={onJump}>
        <span className="block text-[11px] text-faint">Suggested edit · {path}{s.anchor.line ? ` · line ${s.anchor.line}` : ''}</span>
        <span className="mt-1 block rounded bg-danger/10 px-1.5 py-0.5 font-mono text-[11px] text-ink line-through decoration-danger/70">{s.original_text || '∅ (insertion)'}</span>
        <span className="mt-0.5 block rounded bg-success/10 px-1.5 py-0.5 font-mono text-[11px] text-ink">{s.proposed_text || '∅ (deletion)'}</span>
      </button>
      <p className="mt-1 text-xs text-muted"><b className="font-medium text-ink">{s.author_name}</b> · {timeAgo(s.created_at)}{s.note ? ` — ${s.note}` : ''}</p>
      {(canWrite || mine) && (
        <div className="mt-1.5 flex gap-1">
          {canWrite && <button className="btn-primary px-2 py-1 text-xs" onClick={() => act('accept')}><Check size={12} /> Accept</button>}
          <button className="btn-ghost px-2 py-1 text-xs" onClick={() => act('reject')}><X size={12} /> {mine && !canWrite ? 'Withdraw' : 'Reject'}</button>
        </div>
      )}
    </div>
  );
}
