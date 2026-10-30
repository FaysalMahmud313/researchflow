import { useEffect, useRef, useState, type ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, Info, Loader2, X } from 'lucide-react';
import { useApp } from '../lib/app';
import { initials } from '../lib/text';
import { avatarUrl, useAvatarVersion } from '../lib/avatars';

/** Research collaboration signal: concentric pulse rings with an upward vector (not a hand emoji). */
export function ResearchSignalIcon({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      <circle cx="12" cy="13" r="2.5" />
      <path d="M6.6 7.6a7.6 7.6 0 0 0 0 10.8" />
      <path d="M17.4 7.6a7.6 7.6 0 0 1 0 10.8" />
      <path d="M12 2v6" />
      <path d="m9.5 4.5 2.5-2.5 2.5 2.5" />
    </svg>
  );
}

export function Spinner({ size = 16, className = '' }: { size?: number; className?: string }) {
  return <Loader2 size={size} className={`animate-spin ${className}`} aria-label="Loading" />;
}

// Default avatars: initials on a gradient picked from the person's id, so people stay
// recognisable before they add a picture.
const AVATAR_GRADIENTS = [
  ['#6366f1', '#8b5cf6'], ['#2563eb', '#06b6d4'], ['#7c3aed', '#db2777'], ['#0d9488', '#22c55e'],
  ['#ea580c', '#f59e0b'], ['#4f46e5', '#0ea5e9'], ['#be123c', '#f97316'], ['#0891b2', '#6366f1'],
];

function gradientFor(key: string): string {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  const [a, b] = AVATAR_GRADIENTS[h % AVATAR_GRADIENTS.length];
  return `linear-gradient(135deg, ${a}, ${b})`;
}

/**
 * A person's picture, or their initials while it loads, when they have none, or if it
 * fails. The box size is fixed, so swapping initials for the picture never shifts layout.
 * Pass `version` when it is already known (the signed-in user); otherwise it is looked up.
 */
export function Avatar({ name, userId, version, size = 24, title, className = '' }: {
  name: string; userId?: string | null; version?: string | null; size?: number; title?: string; className?: string;
}) {
  const v = useAvatarVersion(userId, version);
  const [failed, setFailed] = useState<string | null>(null);
  const showImage = !!(userId && v && failed !== v);
  return (
    <span
      title={title ?? name}
      className={`relative inline-flex shrink-0 select-none items-center justify-center overflow-hidden rounded-full font-semibold text-white ring-2 ring-surface ${className}`}
      style={{ width: size, height: size, fontSize: Math.max(9, size * 0.38), background: gradientFor(userId || name) }}
    >
      <span aria-hidden={showImage}>{initials(name)}</span>
      {showImage && (
        <img
          src={avatarUrl(userId, v)}
          alt=""
          width={size}
          height={size}
          loading="lazy"
          decoding="async"
          draggable={false}
          onError={() => setFailed(v)}
          className="absolute inset-0 h-full w-full object-cover"
        />
      )}
    </span>
  );
}

const STATUS_STYLE: Record<string, string> = {
  'Working Draft': 'bg-slate-500/10 text-slate-600 dark:text-slate-300',
  Drafting: 'bg-slate-500/10 text-slate-600 dark:text-slate-300',
  'Research in Progress': 'bg-sky-500/10 text-sky-700 dark:text-sky-300',
  'Internal Review': 'bg-amber-500/10 text-amber-700 dark:text-amber-300',
  'Under Internal Review': 'bg-amber-500/10 text-amber-700 dark:text-amber-300',
  'Ready for Submission': 'bg-teal-500/10 text-teal-700 dark:text-teal-300',
  Submitted: 'bg-blue-500/10 text-blue-700 dark:text-blue-300',
  'Under Review': 'bg-violet-500/10 text-violet-700 dark:text-violet-300',
  'Revision Requested': 'bg-orange-500/10 text-orange-700 dark:text-orange-300',
  Accepted: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  Published: 'bg-emerald-600/15 text-emerald-700 dark:text-emerald-300',
  Rejected: 'bg-rose-500/10 text-rose-700 dark:text-rose-300',
  Archived: 'bg-slate-500/10 text-slate-500 dark:text-slate-400',
};

export function StatusBadge({ status }: { status: string }) {
  return <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLE[status] ?? 'bg-raised text-muted'}`}>{status}</span>;
}

export function RoleBadge({ role }: { role: string }) {
  return <span className="chip capitalize">{role}</span>;
}

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      {icon && <div className="text-faint">{icon}</div>}
      <p className="font-medium text-ink">{title}</p>
      {children && <p className="max-w-sm text-sm text-muted">{children}</p>}
      {action}
    </div>
  );
}

export function SkeletonRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-3" aria-busy="true">
      {Array.from({ length: rows }).map((_, i) => <div key={i} className="skeleton h-9" />)}
    </div>
  );
}

export function Modal({ open, onClose, title, children, footer, wide }: { open: boolean; onClose(): void; title: string; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    setTimeout(() => ref.current?.querySelector<HTMLElement>('input,textarea,select,button[data-autofocus]')?.focus(), 0);
    return () => {
      window.removeEventListener('keydown', onKey);
      prev?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-[8vh]" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title} className={`card w-full ${wide ? 'max-w-3xl' : 'max-w-lg'} shadow-pop`}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="text-[15px] font-semibold">{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto p-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-4 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function ConfirmDialog({ open, title, message, confirmLabel, danger, onConfirm, onClose }: { open: boolean; title: string; message: ReactNode; confirmLabel: string; danger?: boolean; onConfirm(): void | Promise<void>; onClose(): void }) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button
            data-autofocus
            className={danger ? 'btn-danger' : 'btn-primary'}
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm();
                onClose();
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy && <Spinner size={14} />} {confirmLabel}
          </button>
        </>
      }
    >
      <div className="text-sm text-muted">{message}</div>
    </Modal>
  );
}

export function Toasts() {
  const { toasts, dismissToast } = useApp();
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex flex-col gap-2" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className="pointer-events-auto flex max-w-sm items-start gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-sm shadow-pop">
          {t.kind === 'success' ? <CheckCircle2 size={16} className="mt-0.5 text-success" /> : t.kind === 'error' ? <AlertTriangle size={16} className="mt-0.5 text-danger" /> : <Info size={16} className="mt-0.5 text-accent" />}
          <span className="flex-1">{t.text}</span>
          <button className="text-faint hover:text-ink" onClick={() => dismissToast(t.id)} aria-label="Dismiss"><X size={14} /></button>
        </div>
      ))}
    </div>
  );
}

/** Dropdown that closes on outside click / Escape. */
export function Dropdown({ trigger, children, align = 'left', open, setOpen }: { trigger: ReactNode; children: ReactNode; align?: 'left' | 'right'; open: boolean; setOpen(v: boolean): void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, setOpen]);
  return (
    <div ref={ref} className="relative">
      {trigger}
      {open && <div className={`menu mt-1 ${align === 'right' ? 'right-0' : 'left-0'}`} onClick={() => setOpen(false)}>{children}</div>}
    </div>
  );
}

export function useErrorToast(): (e: unknown) => void {
  const { toast } = useApp();
  return (e: unknown) => toast(e instanceof Error ? e.message : 'Something went wrong.', 'error');
}
