import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { ArrowLeft, ArrowRight, AtSign, Check, KeyRound, Lock, Mail, Monitor, Moon, ShieldCheck, Sun, User, X } from 'lucide-react';
import { api, ApiError } from '../services/apiClient';
import { navigate, useApp } from '../lib/app';
import { ResearchSignalIcon, Spinner } from '../components/ui';
import { BrandPanel } from './auth/BrandPanel';
import { AuthField, DEFAULT_POLICY, Notice, PasswordField, PasswordStrength, Steps, checkPassword, type PasswordPolicy } from './auth/fields';
import type { SessionUser, ThemeMode } from '../types';

type Mode = 'login' | 'register-email' | 'register-details' | 'verify' | 'forgot' | 'reset';
type Banner = { kind: 'error' | 'success' | 'info'; content: ReactNode } | null;

// Preliminary format check for instant feedback; the server validates every address again.
const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[A-Za-z]{2,}$/;
const USERNAME_SHAPE = /^[a-zA-Z0-9_.-]{3,32}$/;

/** Read a link from an email: #/auth/verify/<code> or #/auth/reset/<code>. */
function linkFromHash(): { mode: 'verify' | 'reset'; code: string } | null {
  const m = /^#\/auth\/(verify|reset)\/([A-Za-z0-9_-]{16,256})$/.exec(window.location.hash);
  return m ? { mode: m[1] as 'verify' | 'reset', code: m[2] } : null;
}

function suggestUsername(fullName: string): string {
  return fullName
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .trim()
    .replace(/\s+/g, '.')
    .replace(/[^a-z0-9_.-]/g, '')
    .slice(0, 32);
}

function friendly(err: unknown): string {
  if (!(err instanceof ApiError)) return 'Something went wrong. Please try again.';
  if (err.status === 429) return 'Too many attempts. Wait a minute, then try again.';
  if (err.status === 0) return "Can't reach ResearchFlow. Check your connection and try again.";
  return err.message;
}

export function AuthPage() {
  const { user, setSession, updateUser, toast } = useApp();
  const link = useRef(linkFromHash());
  const [mode, setMode] = useState<Mode>(link.current?.mode ?? 'login');
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [form, setForm] = useState({
    identifier: '', password: '', remember: false,
    email: '', full_name: '', username: '', newPassword: '', confirm: '', code: link.current?.code ?? '',
  });
  const [usernameEdited, setUsernameEdited] = useState(false);
  const [usernameCheck, setUsernameCheck] = useState<{ value: string; available: boolean; reason: string } | null>(null);
  const [policy, setPolicy] = useState<PasswordPolicy>(DEFAULT_POLICY);
  const [devNote, setDevNote] = useState<string | null>(null);
  // After sign-up the address is known; from an email link it may not be.
  const [emailKnown, setEmailKnown] = useState(false);

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    setErrors((e) => (e[key] ? { ...e, [key]: '' } : e));
  };

  const go = (next: Mode, nextBanner: Banner = null) => {
    setMode(next);
    setBanner(nextBanner);
    setErrors({});
    setDevNote(null);
  };

  // The code from an email link is now in the form; keep it out of the address bar and history.
  useEffect(() => {
    if (link.current) window.history.replaceState(null, '', window.location.pathname + window.location.search);
  }, []);

  useEffect(() => {
    if (mode === 'register-details' || mode === 'reset') {
      api.get<PasswordPolicy>('/auth/password-policy').then(setPolicy).catch(() => undefined);
    }
  }, [mode]);

  // Suggest a username from the name until the person types their own.
  useEffect(() => {
    if (!usernameEdited) setForm((f) => ({ ...f, username: suggestUsername(f.full_name) }));
  }, [form.full_name, usernameEdited]);

  // Live username availability (debounced).
  useEffect(() => {
    const value = form.username.trim().toLowerCase();
    if (mode !== 'register-details' || !USERNAME_SHAPE.test(value)) {
      setUsernameCheck(null);
      return;
    }
    const t = window.setTimeout(() => {
      api
        .get<{ username: string; available: boolean; reason: string }>(`/auth/username-available?username=${encodeURIComponent(value)}`)
        .then((r) => setUsernameCheck({ value, available: r.available, reason: r.reason }))
        .catch(() => setUsernameCheck(null));
    }, 350);
    return () => window.clearTimeout(t);
  }, [form.username, mode]);

  const finishVerification = () => {
    if (user) {
      updateUser({ email_verified: true });
      toast('Email verified.', 'success');
      navigate({ name: 'section', section: 'overview' });
    } else {
      go('login', { kind: 'success', content: 'Email verified. Sign in to continue.' });
    }
  };

  // Opening a verification link verifies right away (the code is single-use).
  const autoVerified = useRef(false);
  useEffect(() => {
    if (link.current?.mode !== 'verify' || autoVerified.current) return;
    autoVerified.current = true;
    setBusy(true);
    api
      .post('/auth/verify-email', { token: link.current.code })
      .then(finishVerification)
      .catch((err) => setBanner({ kind: 'error', content: verifyError(err) }))
      .finally(() => setBusy(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const verifyError = (err: unknown): ReactNode =>
    err instanceof ApiError && err.status === 400
      ? 'This code is invalid, already used, or expired. Request a new one below.'
      : friendly(err);

  const run = async (task: () => Promise<void>) => {
    if (busy) return; // no duplicate submissions
    setBusy(true);
    setBanner(null);
    try {
      await task();
    } catch (err) {
      setBanner({ kind: 'error', content: friendly(err) });
    } finally {
      setBusy(false);
    }
  };

  // ---- Sign in ---------------------------------------------------------------
  const login = (e: FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!form.identifier.trim()) errs.identifier = 'Enter your username or email.';
    if (!form.password) errs.password = 'Enter your password.';
    setErrors(errs);
    if (Object.keys(errs).length) return;
    void run(async () => {
      try {
        const res = await api.post<{ user: SessionUser; csrf_token: string }>('/auth/login', {
          identifier: form.identifier.trim(), password: form.password, remember_me: form.remember,
        });
        setSession(res.user, res.csrf_token);
        // Arrived from an email link: leave the auth screens for the app.
        if (link.current) navigate({ name: 'section', section: 'overview' });
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          setBanner({ kind: 'error', content: "That username or email and password don't match. Check them and try again." });
          setForm((f) => ({ ...f, password: '' }));
          return;
        }
        throw err;
      }
    });
  };

  // ---- Sign up, step 1 -------------------------------------------------------
  const checkEmail = (e: FormEvent) => {
    e.preventDefault();
    const email = form.email.trim();
    if (!EMAIL_SHAPE.test(email)) {
      setErrors({ email: 'Enter a valid email address, like name@university.edu.' });
      return;
    }
    void run(async () => {
      try {
        const res = await api.post<{ email: string }>('/auth/register/check-email', { email });
        setForm((f) => ({ ...f, email: res.email }));
        go('register-details');
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          setBanner({
            kind: 'info',
            content: (
              <>
                <span className="block font-medium">You already have an account with this email.</span>
                <span className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
                  <button type="button" className="auth-link" onClick={() => { set('identifier', email); go('login'); }}>Sign in instead</button>
                  <button type="button" className="auth-link" onClick={() => go('forgot')}>Reset your password</button>
                </span>
              </>
            ),
          });
          return;
        }
        if (err instanceof ApiError && err.status === 422) {
          setErrors({ email: err.message });
          return;
        }
        throw err;
      }
    });
  };

  // ---- Sign up, step 2 -------------------------------------------------------
  const pw = checkPassword(form.newPassword, policy);
  const usernameValue = form.username.trim().toLowerCase();
  const usernameStatus = !usernameValue
    ? null
    : !USERNAME_SHAPE.test(usernameValue)
      ? { ok: false, text: '3–32 characters: letters, numbers, dots, dashes or underscores.' }
      : usernameCheck?.value === usernameValue
        ? { ok: usernameCheck.available, text: usernameCheck.available ? 'Available' : usernameCheck.reason || 'That username is taken.' }
        : null;

  const createAccount = (e: FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (form.full_name.trim().length < 2) errs.full_name = 'Enter your full name.';
    if (!USERNAME_SHAPE.test(usernameValue)) errs.username = 'Use 3–32 letters, numbers, dots, dashes or underscores.';
    else if (usernameStatus && !usernameStatus.ok) errs.username = usernameStatus.text;
    if (!pw.meetsPolicy) errs.newPassword = 'Your password does not meet all the requirements yet.';
    if (!form.confirm) errs.confirm = 'Enter your password again.';
    else if (form.confirm !== form.newPassword) errs.confirm = "Passwords don't match.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    void run(async () => {
      try {
        const res = await api.post<{ verification_email_sent?: boolean; dev_verification_token?: string }>('/auth/register', {
          full_name: form.full_name.trim(), username: usernameValue, email: form.email, password: form.newPassword,
        });
        setForm((f) => ({ ...f, identifier: usernameValue, newPassword: '', confirm: '', code: res.dev_verification_token ?? '' }));
        if (res.verification_email_sent || res.dev_verification_token) {
          setEmailKnown(true);
          go('verify', {
            kind: 'success',
            content: res.verification_email_sent
              ? <>Account created. We sent a verification link to <b>{form.email}</b>.</>
              : <>Account created for <b>{form.email}</b>.</>,
          });
          if (!res.verification_email_sent) setDevNote('Development mode: no email was sent, so the code is filled in for you.');
        } else {
          go('login', { kind: 'success', content: 'Account created. Sign in to start your first project.' });
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 409 && /username/i.test(err.message)) {
          setErrors({ username: err.message });
          return;
        }
        if (err instanceof ApiError && err.status === 409) {
          go('register-email', { kind: 'error', content: err.message });
          return;
        }
        throw err;
      }
    });
  };

  // ---- Verify ------------------------------------------------------------------
  const verify = (e: FormEvent) => {
    e.preventDefault();
    if (!form.code.trim()) {
      setErrors({ code: 'Paste the code from the email.' });
      return;
    }
    void run(async () => {
      try {
        await api.post('/auth/verify-email', { token: form.code.trim() });
        finishVerification();
      } catch (err) {
        setBanner({ kind: 'error', content: verifyError(err) });
      }
    });
  };

  const resend = () => {
    const email = form.email.trim() || user?.email || '';
    if (!EMAIL_SHAPE.test(email)) {
      setErrors({ email: 'Enter the email you registered with.' });
      return;
    }
    void run(async () => {
      const res = await api.post<{ email_delivery: boolean; dev_verification_token?: string }>('/auth/resend-verification', { email });
      if (!res.email_delivery && !res.dev_verification_token) {
        setBanner({ kind: 'error', content: "This server can't send email yet. Ask your administrator to verify your address." });
        return;
      }
      if (res.dev_verification_token) set('code', res.dev_verification_token);
      setBanner({ kind: 'info', content: 'If that address has an unverified account, a new code is on its way. Older codes no longer work.' });
    });
  };

  // ---- Forgot / reset ------------------------------------------------------------
  const forgot = (e: FormEvent) => {
    e.preventDefault();
    const email = form.email.trim();
    if (!EMAIL_SHAPE.test(email)) {
      setErrors({ email: 'Enter a valid email address.' });
      return;
    }
    void run(async () => {
      const res = await api.post<{ email_delivery?: boolean; dev_reset_token?: string }>('/auth/forgot-password', { email });
      if (!res.email_delivery && !res.dev_reset_token) {
        setBanner({ kind: 'error', content: "This server can't send email yet. Ask your administrator to reset your password." });
        return;
      }
      setForm((f) => ({ ...f, code: res.dev_reset_token ?? '', newPassword: '', confirm: '' }));
      if (res.email_delivery) {
        go('reset', { kind: 'info', content: 'If an account uses that address, we sent a reset link to it. The link works once, for 30 minutes.' });
      } else {
        go('reset');
        setDevNote('Development mode: no email was sent, so the code is filled in for you.');
      }
    });
  };

  const reset = (e: FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!form.code.trim()) errs.code = 'Paste the code from the email.';
    if (!pw.meetsPolicy) errs.newPassword = 'Your password does not meet all the requirements yet.';
    if (form.confirm !== form.newPassword) errs.confirm = "Passwords don't match.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    void run(async () => {
      try {
        await api.post('/auth/reset-password', { token: form.code.trim(), new_password: form.newPassword });
        setForm((f) => ({ ...f, newPassword: '', confirm: '', code: '', password: '' }));
        go('login', { kind: 'success', content: 'Password updated, and you were signed out everywhere else. Sign in with your new password.' });
      } catch (err) {
        if (err instanceof ApiError && err.status === 400) {
          setBanner({
            kind: 'error',
            content: (
              <>
                This reset link is invalid, already used, or expired.{' '}
                <button type="button" className="auth-link" onClick={() => go('forgot')}>Request a new one</button>
              </>
            ),
          });
          return;
        }
        throw err;
      }
    });
  };

  const confirmMatches = !!form.confirm && form.confirm === form.newPassword;

  return (
    <div className="auth-shell flex min-h-full">
      <BrandPanel />
      <div className="relative flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between px-5 pt-5 sm:px-8">
          <span className="flex items-center gap-2 text-ink lg:invisible">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-accent-ink"><ResearchSignalIcon className="h-[18px] w-[18px]" /></span>
            <span className="text-[16px] font-semibold tracking-tight">ResearchFlow</span>
          </span>
          <ThemeSwitch />
        </header>

        <main className="flex flex-1 items-center justify-center px-4 py-8 sm:px-8">
          <div className="w-full max-w-[420px]">
            <div key={mode} className="auth-card auth-enter">
              {mode === 'login' && (
                <form onSubmit={login} noValidate className="space-y-5">
                  <Heading title="Welcome back" text="Sign in to continue to your research workspace." />
                  {banner && <Notice kind={banner.kind}>{banner.content}</Notice>}
                  {import.meta.env.DEV && <DemoHint onUse={(id, pass) => setForm((f) => ({ ...f, identifier: id, password: pass }))} />}
                  <AuthField
                    label="Username or email" icon={AtSign} name="username" autoComplete="username" autoFocus
                    placeholder="name@example.com or username" value={form.identifier}
                    onChange={(e) => set('identifier', e.target.value)} error={errors.identifier}
                  />
                  <PasswordField
                    label="Password" icon={Lock} name="password" autoComplete="current-password"
                    placeholder="Your password" value={form.password}
                    onChange={(e) => set('password', e.target.value)} error={errors.password}
                    labelAside={<button type="button" className="auth-link text-[12.5px]" onClick={() => go('forgot')}>Forgot password?</button>}
                  />
                  <label className="flex cursor-pointer items-center gap-2.5 text-[13px] text-muted">
                    <input type="checkbox" className="auth-check" checked={form.remember} onChange={(e) => set('remember', e.target.checked)} />
                    Keep me signed in on this device
                  </label>
                  <SubmitButton busy={busy} busyText="Signing in…">Sign in</SubmitButton>
                  <SwitchLine text="New to ResearchFlow?" action="Create an account" onClick={() => go('register-email')} />
                </form>
              )}

              {mode === 'register-email' && (
                <form onSubmit={checkEmail} noValidate className="space-y-5">
                  <Steps step={1} />
                  <Heading title="Let's get your research workspace ready" text="Start with your email. You'll use it to sign in and to recover your account." />
                  {banner && <Notice kind={banner.kind}>{banner.content}</Notice>}
                  <AuthField
                    label="Email address" icon={Mail} type="email" name="email" autoComplete="email" autoFocus inputMode="email"
                    placeholder="you@example.com" value={form.email}
                    onChange={(e) => set('email', e.target.value)} error={errors.email}
                  />
                  <SubmitButton busy={busy} busyText="Checking…">Continue</SubmitButton>
                  <SwitchLine text="Already have an account?" action="Sign in" onClick={() => go('login')} />
                </form>
              )}

              {mode === 'register-details' && (
                <form onSubmit={createAccount} noValidate className="space-y-5">
                  <Steps step={2} />
                  <Heading title="Create your profile" text="This is how your co-authors will see you." />
                  <div className="flex items-center gap-3 rounded-xl border border-line bg-raised/60 px-3.5 py-2.5">
                    <Mail size={16} className="shrink-0 text-accent" aria-hidden="true" />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[11.5px] text-muted">Registering</span>
                      <span className="block truncate text-[13.5px] font-medium">{form.email}</span>
                    </span>
                    <button type="button" className="auth-link text-[12.5px]" onClick={() => go('register-email')}>Change</button>
                  </div>
                  {banner && <Notice kind={banner.kind}>{banner.content}</Notice>}
                  <AuthField
                    label="Full name" icon={User} name="name" autoComplete="name" autoFocus
                    placeholder="Faysal Mahmud" value={form.full_name}
                    onChange={(e) => set('full_name', e.target.value)} error={errors.full_name}
                  />
                  <AuthField
                    label="Username" icon={AtSign} name="new-username" autoComplete="username" autoCapitalize="none" spellCheck={false}
                    placeholder="faysal.mahmud" value={form.username}
                    onChange={(e) => { setUsernameEdited(true); set('username', e.target.value); }}
                    error={errors.username}
                    hint={usernameStatus ? (
                      <span className={`flex items-center gap-1 ${usernameStatus.ok ? 'text-success' : 'text-danger'}`}>
                        {usernameStatus.ok ? <Check size={13} /> : <X size={13} />} {usernameStatus.text}
                      </span>
                    ) : 'Your public handle for mentions and invitations.'}
                  />
                  <PasswordField
                    label="Password" icon={Lock} name="new-password" autoComplete="new-password"
                    placeholder="Create a strong password" value={form.newPassword}
                    onChange={(e) => set('newPassword', e.target.value)} error={errors.newPassword}
                  />
                  <PasswordStrength password={form.newPassword} policy={policy} />
                  <PasswordField
                    label="Confirm password" icon={ShieldCheck} name="confirm-password" autoComplete="new-password"
                    placeholder="Enter your password again" value={form.confirm}
                    onChange={(e) => set('confirm', e.target.value)} error={errors.confirm}
                    hint={form.confirm ? (confirmMatches
                      ? <span className="flex items-center gap-1 text-success"><Check size={13} /> Passwords match</span>
                      : <span className="text-muted">Keep typing… the passwords don't match yet.</span>) : undefined}
                  />
                  <p className="text-[12.5px] text-muted">You can add a profile picture after signing in, from Account &amp; Settings.</p>
                  <div className="flex gap-2.5">
                    <button type="button" className="auth-secondary" onClick={() => go('register-email')}>
                      <ArrowLeft size={16} aria-hidden="true" /> Back
                    </button>
                    <SubmitButton busy={busy} busyText="Creating account…" className="flex-1">Create account</SubmitButton>
                  </div>
                </form>
              )}

              {mode === 'verify' && (
                <form onSubmit={verify} noValidate className="space-y-5">
                  <IconBadge icon={Mail} />
                  <Heading title="Verify your email" text="Open the link we emailed you, or paste the code from it here." />
                  {banner && <Notice kind={banner.kind}>{banner.content}</Notice>}
                  {devNote && <Notice kind="info">{devNote}</Notice>}
                  <AuthField
                    label="Verification code" icon={KeyRound} name="one-time-code" autoComplete="one-time-code" spellCheck={false}
                    placeholder="Paste the code from the email" value={form.code} className="font-mono text-[13px]"
                    onChange={(e) => set('code', e.target.value)} error={errors.code}
                  />
                  <SubmitButton busy={busy} busyText="Verifying…">Verify email</SubmitButton>
                  {!user && !emailKnown && (
                    <AuthField
                      label="Email you registered with" icon={Mail} type="email" name="email" autoComplete="email"
                      placeholder="you@example.com" value={form.email}
                      onChange={(e) => set('email', e.target.value)} error={errors.email}
                      hint="Needed only to send a new code."
                    />
                  )}
                  <div className="space-y-2 text-center text-[13px] text-muted">
                    <p>
                      No email, or the code expired?{' '}
                      <button type="button" className="auth-link" onClick={resend} disabled={busy}>Send a new code</button>
                    </p>
                    <p>
                      {user
                        ? <button type="button" className="auth-link" onClick={() => navigate({ name: 'section', section: 'overview' })}>Continue to ResearchFlow</button>
                        : <button type="button" className="auth-link" onClick={() => go('login')}>Skip for now and sign in</button>}
                    </p>
                  </div>
                </form>
              )}

              {mode === 'forgot' && (
                <form onSubmit={forgot} noValidate className="space-y-5">
                  <IconBadge icon={KeyRound} />
                  <Heading title="Reset your password" text="Enter the email on your account and we'll send you a reset link." />
                  {banner && <Notice kind={banner.kind}>{banner.content}</Notice>}
                  <AuthField
                    label="Email address" icon={Mail} type="email" name="email" autoComplete="email" autoFocus inputMode="email"
                    placeholder="you@example.com" value={form.email}
                    onChange={(e) => set('email', e.target.value)} error={errors.email}
                  />
                  <SubmitButton busy={busy} busyText="Sending…">Send reset link</SubmitButton>
                  <BackLink onClick={() => go('login')} />
                </form>
              )}

              {mode === 'reset' && (
                <form onSubmit={reset} noValidate className="space-y-5">
                  <IconBadge icon={Lock} />
                  <Heading title="Choose a new password" text="You'll be signed out of every other device." />
                  {banner && <Notice kind={banner.kind}>{banner.content}</Notice>}
                  {devNote && <Notice kind="info">{devNote}</Notice>}
                  <AuthField
                    label="Reset code" icon={KeyRound} name="one-time-code" autoComplete="one-time-code" spellCheck={false}
                    placeholder="Paste the code from the email" value={form.code} className="font-mono text-[13px]"
                    onChange={(e) => set('code', e.target.value)} error={errors.code}
                  />
                  <PasswordField
                    label="New password" icon={Lock} name="new-password" autoComplete="new-password"
                    placeholder="Create a strong password" value={form.newPassword}
                    onChange={(e) => set('newPassword', e.target.value)} error={errors.newPassword}
                  />
                  <PasswordStrength password={form.newPassword} policy={policy} />
                  <PasswordField
                    label="Confirm new password" icon={ShieldCheck} name="confirm-password" autoComplete="new-password"
                    placeholder="Enter your password again" value={form.confirm}
                    onChange={(e) => set('confirm', e.target.value)} error={errors.confirm}
                    hint={form.confirm && confirmMatches ? <span className="flex items-center gap-1 text-success"><Check size={13} /> Passwords match</span> : undefined}
                  />
                  <SubmitButton busy={busy} busyText="Updating…">Update password</SubmitButton>
                  <BackLink onClick={() => go('login')} />
                </form>
              )}
            </div>
          </div>
        </main>
        <footer className="px-6 pb-5 text-center text-[12px] text-faint">Your session is protected with secure, HTTP-only cookies.</footer>
      </div>
    </div>
  );
}

function Heading({ title, text }: { title: string; text: string }) {
  return (
    <div>
      <h1 className="text-[22px] font-semibold leading-tight tracking-tight text-ink sm:text-[24px]">{title}</h1>
      <p className="mt-1.5 text-[14px] leading-relaxed text-muted">{text}</p>
    </div>
  );
}

function IconBadge({ icon: Icon }: { icon: typeof Mail }) {
  return (
    <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-accent/10 text-accent ring-1 ring-accent/20">
      <Icon size={20} aria-hidden="true" />
    </span>
  );
}

function SubmitButton({ busy, busyText, children, className = '' }: { busy: boolean; busyText: string; children: ReactNode; className?: string }) {
  return (
    <button type="submit" className={`auth-primary group ${className}`} disabled={busy} aria-busy={busy}>
      {busy ? <><Spinner size={16} /> {busyText}</> : <>{children} <ArrowRight size={16} aria-hidden="true" className="transition-transform group-hover:translate-x-0.5" /></>}
    </button>
  );
}

function SwitchLine({ text, action, onClick }: { text: string; action: string; onClick(): void }) {
  return (
    <p className="border-t border-line pt-5 text-center text-[13.5px] text-muted">
      {text} <button type="button" className="auth-link font-semibold" onClick={onClick}>{action}</button>
    </p>
  );
}

function BackLink({ onClick }: { onClick(): void }) {
  return (
    <button type="button" onClick={onClick} className="mx-auto flex items-center gap-1.5 text-[13px] font-medium text-muted hover:text-ink">
      <ArrowLeft size={15} aria-hidden="true" /> Back to sign in
    </button>
  );
}

function ThemeSwitch() {
  const { theme, setTheme } = useApp();
  const options: { id: ThemeMode; icon: typeof Sun; label: string }[] = [
    { id: 'light', icon: Sun, label: 'Light theme' },
    { id: 'dark', icon: Moon, label: 'Dark theme' },
    { id: 'system', icon: Monitor, label: 'Use system theme' },
  ];
  return (
    <div className="flex rounded-full border border-line bg-surface/80 p-0.5 shadow-sm backdrop-blur" role="radiogroup" aria-label="Theme">
      {options.map(({ id, icon: Icon, label }) => (
        <button
          key={id}
          type="button"
          role="radio"
          aria-checked={theme === id}
          aria-label={label}
          title={label}
          onClick={() => setTheme(id)}
          className={`flex h-7 w-7 items-center justify-center rounded-full transition-colors ${theme === id ? 'bg-accent text-accent-ink' : 'text-muted hover:text-ink'}`}
        >
          <Icon size={14} />
        </button>
      ))}
    </div>
  );
}

/** Development builds only: offers the seeded demo account (the server answers 404 outside development). */
function DemoHint({ onUse }: { onUse(identifier: string, password: string): void }) {
  const [demo, setDemo] = useState<{ username: string; password: string } | null>(null);
  useEffect(() => {
    api.get<{ username: string; password: string }>('/auth/dev-demo').then(setDemo).catch(() => setDemo(null));
  }, []);
  if (!demo) return null;
  return (
    <div className="flex items-center gap-3 rounded-xl border border-dashed border-accent/40 bg-accent/[0.05] px-3.5 py-2.5 text-[12.5px]">
      <span className="min-w-0 flex-1">
        <span className="block font-medium text-ink">Local demo account</span>
        <span className="block truncate font-mono text-muted">{demo.username} · {demo.password}</span>
      </span>
      <button type="button" className="auth-link shrink-0 font-semibold" onClick={() => onUse(demo.username, demo.password)}>Use it</button>
    </div>
  );
}
