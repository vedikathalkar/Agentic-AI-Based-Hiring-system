import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import Logo from '../../components/Logo';
import { api, roleForPath } from '../../api';
import { useApp } from '../../context/AppContext';
import { STORIES } from './authScenes';
import StoryStage from './StoryStage';
import '../../styles/auth.css';

const CHAPTER_MS = 6500;
// The page a protected route sent the user away from is only a valid destination inside the portal they are signing in to.
const returnTo = (from, audience) => {
  if (typeof from !== 'string' || !from.startsWith('/') || from.startsWith('//')) return PATHS[audience].home;
  const portal = roleForPath(from.split(/[?#]/)[0]);
  return portal === (audience === 'ent' ? 'hr' : 'candidate') ? from : PATHS[audience].home;
};
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const STRENGTH_COLORS = ['#FF6B81', '#FFA24A', '#FFC53D', '#9BE36B'];

const PATHS = {
  talent: { in: '/login', up: '/signup', home: '/dashboard', onboard: '/profile' },
  ent: { in: '/hr/login', up: '/hr/signup', home: '/hr', onboard: '/hr/company' },
};

function strength(v) {
  let s = 0;
  if (v.length >= 8) s += 1;
  if (/\d/.test(v)) s += 1;
  if (/[A-Z]/.test(v) && /[a-z]/.test(v)) s += 1;
  if (/[^A-Za-z0-9]/.test(v)) s += 1;
  return s;
}

/**
 * Sign in / create account for both portals. The audience (Candidate or Enterprise) and the mode come
 * from the URL, so /login, /signup, /hr/login and /hr/signup all land here and remain linkable.
 */
export default function AuthPage({ role = 'talent', mode = 'in' }) {
  const ent = role === 'ent';
  const up = mode === 'up';
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useApp();
  const message = location.state?.message;
  const referral = !ent ? new URLSearchParams(location.search).get('ref') || '' : '';

  const [name, setName] = useState('');
  const [company, setCompany] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [show, setShow] = useState(false);
  const [errors, setErrors] = useState({});
  const [formError, setFormError] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');

  // ---- the story ----
  const story = STORIES[role];
  const [chapter, setChapter] = useState(0);
  const [swapping, setSwapping] = useState(false);
  const reduce = useMemo(() => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches, []);
  const current = story[Math.min(chapter, story.length - 1)];

  useEffect(() => { setChapter(0); }, [role]);

  useEffect(() => {
    if (reduce) return undefined;
    const t = setTimeout(() => setChapter((c) => (c + 1) % story.length), CHAPTER_MS);
    return () => clearTimeout(t);
  }, [chapter, role, reduce, story.length]);

  // the headline fades out, swaps, fades back in
  const shown = useRef(current);
  const [text, setText] = useState(current);
  useEffect(() => {
    if (shown.current === current) return undefined;
    shown.current = current;
    setSwapping(true);
    const t = setTimeout(() => { setText(current); setSwapping(false); }, reduce ? 0 : 260);
    return () => clearTimeout(t);
  }, [current, reduce]);

  // ---- navigation between modes / audiences keeps the URL meaningful ----
  const go = (nextRole, nextMode) => {
    setErrors({}); setFormError(''); setNote('');
    navigate(PATHS[nextRole][nextMode] + (nextRole === 'talent' && referral ? `?ref=${encodeURIComponent(referral)}` : ''),
      { replace: true, state: location.state });
  };

  const score = strength(password);

  const validate = () => {
    const e = {};
    if (up && !name.trim()) e.name = 'Enter your name.';
    if (up && ent && !company.trim()) e.company = 'Enter your company name.';
    if (!EMAIL_RE.test(email.trim())) e.email = 'Enter a valid email, like you@example.com.';
    if (!password) e.password = 'Enter your password.';
    else if (up && (password.length < 8 || !/\d/.test(password))) e.password = 'Use at least 8 characters with a number.';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const submit = async (ev) => {
    ev.preventDefault();
    setFormError(''); setNote('');
    if (!validate()) return;
    setBusy(true);
    const creds = { email: email.trim(), password };
    try {
      if (ent) {
        if (up) {
          await api.hrSignup({ name: name.trim(), company: company.trim(), ...creds });
          login(await api.hrLogin(creds));
          navigate(PATHS.ent.onboard, { replace: true });
        } else {
          login(await api.hrLogin(creds));
          navigate(returnTo(location.state?.from, 'ent'), { replace: true });
        }
      } else if (up) {
        await api.candidateSignup({ name: name.trim(), ...creds, referral_code: referral || undefined });
        login(await api.candidateLogin(creds));            // the account exists now; sign straight in
        navigate(PATHS.talent.onboard, { replace: true });
      } else {
        login(await api.candidateLogin(creds));
        navigate(returnTo(location.state?.from, 'talent'), { replace: true });
      }
    } catch (err) {
      setFormError(err.message || 'Something went wrong. Please try again.');
    } finally { setBusy(false); }
  };

  const title = up ? (ent ? 'Start hiring.' : 'Create your profile.') : 'Welcome back.';
  const sub = up
    ? (ent ? 'Set up your company account in a minute.' : 'It takes a minute. Your resume fills in the rest.')
    : (ent ? 'Sign in to see your roles and ranked applicants.' : 'Sign in to pick up where you left off.');

  return (
    <div className="as-root" style={{ '--tint': current.tint, '--tint-c': current.tc, '--cd': `${CHAPTER_MS / 1000}s` }}>
      <StoryStage role={role} index={chapter} tint={current.tint} />

      <main className="as-ui">
        <section className="as-copy" aria-label="Hirelune story">
          <Link to="/" className="as-logo" aria-label="Hirelune home"><Logo size={30} tone="light" /></Link>
          <div className="as-chap">{text.c}</div>
          <h2 className={`as-hl${swapping ? ' sw' : ''}`}>{text.h}</h2>
          <p className={`as-sp${swapping ? ' sw' : ''}`}>{text.s}</p>
          <div className="as-dots" role="group" aria-label="Story chapters">
            {story.map((c, i) => (
              <button key={c.h + i} type="button" aria-label={`Chapter ${i + 1}`} aria-current={i === chapter}
                      onClick={() => setChapter(i)}>
                <i key={i === chapter ? `${role}-${chapter}` : `${i}-${i < chapter}`}
                   style={i < chapter ? { transform: 'scaleX(1)' } : undefined} />
              </button>
            ))}
            <span className="as-note">Illustrated story</span>
          </div>
        </section>

        <section className="as-formwrap">
          <div className="as-card">
            <div className="as-seg" role="group" aria-label="Sign in or create account">
              <button type="button" className="as-bub" aria-pressed={!up} onClick={() => go(role, 'in')}>Sign in</button>
              <button type="button" className="as-bub" aria-pressed={up} onClick={() => go(role, 'up')}>Create account</button>
            </div>

            <h1 className="as-title">{title}</h1>
            <p className="as-subtitle">{sub}</p>
            {message && <p className="as-banner ok" role="status">{message}</p>}
            {up && referral && <p className="as-banner" role="status">You were invited with referral code <b>{referral}</b>.</p>}

            <div className="as-roles" role="group" aria-label="I am">
              <button type="button" className="as-role as-bub" data-r="talent" aria-pressed={!ent} onClick={() => go('talent', mode)}>
                <b>Candidate</b><span>Find and win roles</span>
              </button>
              <button type="button" className="as-role as-bub" data-r="ent" aria-pressed={ent} onClick={() => go('ent', mode)}>
                <b>Enterprise</b><span>Hire with confidence</span>
              </button>
            </div>

            <form className="as-fields" onSubmit={submit} noValidate>
              {up && (
                <div>
                  <label htmlFor="as-name">{ent ? 'Your name' : 'Full name'}</label>
                  <input id="as-name" className="as-inp" type="text" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)}
                         placeholder="Asha Kulkarni" aria-invalid={!!errors.name} />
                  <div className="as-err" role="alert">{errors.name}</div>
                </div>
              )}
              {up && ent && (
                <div>
                  <label htmlFor="as-company">Company name</label>
                  <input id="as-company" className="as-inp" type="text" autoComplete="organization" value={company} onChange={(e) => setCompany(e.target.value)}
                         placeholder="Northwind Labs" aria-invalid={!!errors.company} />
                  <div className="as-err" role="alert">{errors.company}</div>
                </div>
              )}
              <div>
                <label htmlFor="as-email">{ent ? 'Work email' : 'Email'}</label>
                <input id="as-email" className="as-inp" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)}
                       placeholder={ent ? 'you@company.com' : 'you@example.com'} aria-invalid={!!errors.email} />
                <div className="as-err" role="alert">{errors.email}</div>
              </div>
              <div>
                <div className="as-lrow">
                  <label htmlFor="as-pw">Password</label>
                  {!up && <button type="button" className="as-link" onClick={() => setNote('Password reset by email is not available yet. Ask your administrator or contact support to reset it.')}>Forgot password?</button>}
                </div>
                <div className="as-pwrow">
                  <input id="as-pw" className="as-inp" type={show ? 'text' : 'password'} autoComplete={up ? 'new-password' : 'current-password'}
                         value={password} onChange={(e) => setPassword(e.target.value)}
                         placeholder={up ? 'Create a password' : 'Enter your password'} aria-invalid={!!errors.password} />
                  <button type="button" className="as-show" aria-label={show ? 'Hide password' : 'Show password'} onClick={() => setShow((v) => !v)}>{show ? 'Hide' : 'Show'}</button>
                </div>
                {up && (
                  <>
                    <div className="as-str" aria-hidden="true">
                      {[0, 1, 2, 3].map((k) => <i key={k} style={k < score ? { background: STRENGTH_COLORS[Math.max(0, score - 1)] } : undefined} />)}
                    </div>
                    <div className="as-hint">Use at least 8 characters with a number.</div>
                  </>
                )}
                <div className="as-err" role="alert">{errors.password}</div>
              </div>

              {note && <p className="as-banner" role="status">{note}</p>}
              {formError && <p className="as-banner bad" role="alert">{formError}</p>}

              <button className={`as-cta as-bub${ent ? ' ent' : ''}${busy ? ' busy' : ''}`} type="submit" disabled={busy}>
                <span className="as-spin" aria-hidden="true" />
                <span>{busy ? 'Please wait…' : up ? (ent ? 'Create company account' : 'Create account') : 'Sign in'}</span>
              </button>
            </form>

            <div className="as-or">or</div>
            <button type="button" className="as-gbtn as-bub" disabled title="Google sign-in is not available yet">
              <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M23 12.3c0-.8-.1-1.5-.2-2.2H12v4.2h6.2a5.3 5.3 0 0 1-2.3 3.5v2.9h3.7C21.8 18.7 23 15.8 23 12.3z" /><path fill="#34A853" d="M12 23.5c3.1 0 5.7-1 7.6-2.8l-3.7-2.9c-1 .7-2.3 1.1-3.9 1.1-3 0-5.5-2-6.4-4.7H1.8v3A11.5 11.5 0 0 0 12 23.5z" /><path fill="#FBBC05" d="M5.6 14.2a6.9 6.9 0 0 1 0-4.4v-3H1.8a11.5 11.5 0 0 0 0 10.4z" /><path fill="#EA4335" d="M12 5.1c1.7 0 3.2.6 4.4 1.7l3.3-3.3A11.5 11.5 0 0 0 1.8 6.8l3.8 3c.9-2.7 3.4-4.7 6.4-4.7z" /></svg>
              Continue with Google <small>(coming soon)</small>
            </button>

            <p className="as-switch">
              {up ? 'Already have an account?' : 'New to Hirelune?'}{' '}
              <button type="button" onClick={() => go(role, up ? 'in' : 'up')}>{up ? 'Sign in' : 'Create an account'}</button>
            </p>
            <p className="as-legal">By continuing you agree to our Terms and Privacy Policy.</p>
          </div>
        </section>
      </main>
    </div>
  );
}
