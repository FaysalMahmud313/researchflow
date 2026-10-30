import { forwardRef, useId, useState, type InputHTMLAttributes, type KeyboardEvent, type ReactNode } from 'react';
import { AlertCircle, Check, Eye, EyeOff, type LucideIcon } from 'lucide-react';

type InputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'size'>;

interface FieldProps extends InputProps {
  label: ReactNode;
  icon: LucideIcon;
  error?: string | null;
  hint?: ReactNode;
  /** Extra content on the label row (e.g. a "Forgot password?" link). */
  labelAside?: ReactNode;
  /** Content inside the right edge of the input (e.g. a visibility toggle). */
  trailing?: ReactNode;
}

/** Labelled input with a leading icon. The label is always visible; placeholders are examples only. */
export const AuthField = forwardRef<HTMLInputElement, FieldProps>(function AuthField(
  { label, icon: Icon, error, hint, labelAside, trailing, id, className = '', ...rest },
  ref,
) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const describedBy = error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined;
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={inputId} className="text-[13px] font-medium text-ink">{label}</label>
        {labelAside}
      </div>
      <div className="group relative">
        <Icon
          size={17}
          aria-hidden="true"
          className={`pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 transition-colors ${error ? 'text-danger' : 'text-faint group-focus-within:text-accent'}`}
        />
        <input
          ref={ref}
          id={inputId}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={`auth-input ${trailing ? 'pr-11' : ''} ${error ? 'auth-input-error' : ''} ${className}`}
          {...rest}
        />
        {trailing && <div className="absolute inset-y-0 right-1.5 flex items-center">{trailing}</div>}
      </div>
      {error ? (
        <p id={`${inputId}-error`} className="flex items-start gap-1.5 text-[12.5px] text-danger">
          <AlertCircle size={14} className="mt-px shrink-0" aria-hidden="true" />
          <span>{error}</span>
        </p>
      ) : hint ? (
        <div id={`${inputId}-hint`} className="text-[12.5px] text-muted">{hint}</div>
      ) : null}
    </div>
  );
});

/** Password input: masked by default, an accessible show/hide toggle, and a Caps Lock warning. */
export const PasswordField = forwardRef<HTMLInputElement, Omit<FieldProps, 'trailing' | 'type'>>(function PasswordField(
  { onKeyDown, onKeyUp, onBlur, hint, ...props },
  ref,
) {
  const [visible, setVisible] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const watchCaps = (e: KeyboardEvent<HTMLInputElement>) => setCapsLock(e.getModifierState?.('CapsLock') ?? false);
  return (
    <AuthField
      ref={ref}
      {...props}
      type={visible ? 'text' : 'password'}
      autoCapitalize="none"
      autoCorrect="off"
      spellCheck={false}
      onKeyDown={(e) => { watchCaps(e); onKeyDown?.(e); }}
      onKeyUp={(e) => { watchCaps(e); onKeyUp?.(e); }}
      onBlur={(e) => { setCapsLock(false); onBlur?.(e); }}
      hint={capsLock ? <span className="font-medium text-warn">Caps Lock is on.</span> : hint}
      trailing={
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? 'Hide password' : 'Show password'}
          aria-pressed={visible}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-faint transition-colors hover:bg-raised hover:text-ink"
        >
          {visible ? <EyeOff size={17} /> : <Eye size={17} />}
        </button>
      }
    />
  );
});

export interface PasswordPolicy {
  min_length: number;
  max_length: number;
  rules: { id: string; label: string }[];
}

/** Mirrors backend/app/security/passwords.py; replaced by GET /auth/password-policy when it loads. */
export const DEFAULT_POLICY: PasswordPolicy = {
  min_length: 10,
  max_length: 128,
  rules: [
    { id: 'upper', label: 'An uppercase letter' },
    { id: 'lower', label: 'A lowercase letter' },
    { id: 'digit', label: 'A number' },
  ],
};

const RULE_CHECKS: Record<string, (pw: string) => boolean> = {
  upper: (pw) => /[A-Z]/.test(pw),
  lower: (pw) => /[a-z]/.test(pw),
  digit: (pw) => /[0-9]/.test(pw),
};

export function checkPassword(pw: string, policy: PasswordPolicy) {
  const items = [
    { id: 'length', label: `At least ${policy.min_length} characters`, met: pw.length >= policy.min_length },
    ...policy.rules.map((r) => ({ id: r.id, label: r.label, met: RULE_CHECKS[r.id]?.(pw) ?? false })),
  ];
  const meetsPolicy = items.every((i) => i.met) && pw.length <= policy.max_length;
  // Beyond the required rules, length and symbols are what make a password hard to guess.
  const extras = [pw.length >= 14, /[^A-Za-z0-9]/.test(pw), pw.length >= 18].filter(Boolean).length;
  const level = !pw ? 0 : !meetsPolicy ? 1 : extras === 0 ? 2 : extras === 1 ? 3 : 4;
  return { items, meetsPolicy, level };
}

const LEVELS = [
  { label: '', bar: 'bg-line' },
  { label: 'Too weak', bar: 'bg-danger' },
  { label: 'Fair', bar: 'bg-warn' },
  { label: 'Good', bar: 'bg-accent' },
  { label: 'Strong', bar: 'bg-success' },
];

/** The server's actual rules as a live checklist, plus a strength meter for passwords that pass. */
export function PasswordStrength({ password, policy }: { password: string; policy: PasswordPolicy }) {
  const { items, level } = checkPassword(password, policy);
  return (
    <div className="space-y-2 rounded-xl border border-line bg-raised/50 px-3 py-2.5" aria-live="polite">
      <div className="flex items-center gap-2">
        <div className="flex flex-1 gap-1" aria-hidden="true">
          {[1, 2, 3, 4].map((i) => (
            <span key={i} className={`h-1.5 flex-1 rounded-full transition-colors ${level >= i ? LEVELS[level].bar : 'bg-line'}`} />
          ))}
        </div>
        <span className="w-16 text-right text-[12px] font-medium text-muted">{LEVELS[level].label}</span>
      </div>
      <ul className="grid grid-cols-1 gap-x-3 gap-y-1 sm:grid-cols-2">
        {items.map((i) => (
          <li key={i.id} className={`flex items-center gap-1.5 text-[12.5px] ${i.met ? 'text-success' : 'text-muted'}`}>
            <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${i.met ? 'border-success bg-success text-white' : 'border-line'}`}>
              {i.met && <Check size={11} strokeWidth={3} />}
            </span>
            {i.label}
            <span className="sr-only">{i.met ? ' (done)' : ' (missing)'}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Two-step progress for sign-up. */
export function Steps({ step }: { step: 1 | 2 }) {
  return (
    <div className="mb-5" aria-label={`Step ${step} of 2`}>
      <div className="mb-2 flex items-center justify-between text-[12px] font-medium">
        <span className="text-accent">Step {step} of 2</span>
        <span className="text-muted">{step === 1 ? 'Email' : 'Your profile'}</span>
      </div>
      <div className="flex gap-1.5" aria-hidden="true">
        <span className="h-1 flex-1 rounded-full bg-accent" />
        <span className={`h-1 flex-1 rounded-full transition-colors duration-300 ${step === 2 ? 'bg-accent' : 'bg-line'}`} />
      </div>
    </div>
  );
}

export function Notice({ kind, children }: { kind: 'error' | 'success' | 'info'; children: ReactNode }) {
  const styles = {
    error: 'border-danger/30 bg-danger/[0.07] text-danger',
    success: 'border-success/30 bg-success/[0.08] text-success',
    info: 'border-accent/25 bg-accent/[0.07] text-ink',
  }[kind];
  return (
    <div role={kind === 'error' ? 'alert' : 'status'} className={`rounded-xl border px-3.5 py-2.5 text-[13px] leading-relaxed ${styles}`}>
      {children}
    </div>
  );
}
