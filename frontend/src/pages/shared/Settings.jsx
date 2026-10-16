import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api';
import { useApp } from '../../context/AppContext';
import { Async, PageHeader, useAsync } from '../../components/ui';
import { LOGIN_PATH } from '../../components/navConfig';

const NOTIFS = [
  ['email_notifications', 'Email notifications', 'Master switch for all emails from Hirelune.'],
  ['assessment_notifications', 'Assessment emails', 'Assessment started / completed.'],
  ['interview_notifications', 'Interview emails', 'Scheduled, rescheduled or cancelled interviews.'],
  ['reminder_notifications', 'Reminder emails', 'One day before an interview.'],
  ['offer_notifications', 'Offer emails', 'Offer letters and responses.'],
  ['marketing_notifications', 'Product news', 'Occasional product updates.'],
];

function Toggle({ id, label, hint, checked, onChange, disabled }) {
  return (
    <label className="toggle-row" htmlFor={id}>
      <span><b>{label}</b>{hint && <span className="small muted" style={{ display: 'block' }}>{hint}</span>}</span>
      <input id={id} type="checkbox" role="switch" checked={!!checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
    </label>
  );
}

function SmtpTest({ defaultTo }) {
  const status = useAsync(() => api.smtpStatus(), []);
  const [to, setTo] = useState(defaultTo || '');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const send = async () => {
    setBusy(true); setResult(null);
    try { const r = await api.sendTestEmail(to); setResult({ ok: true, text: `Test email sent to ${r.sent_to}.` }); }
    catch (e) { setResult({ ok: false, text: e.message }); }
    finally { setBusy(false); }
  };
  return (
    <section className="card section" id="email">
      <h3>Email delivery (SMTP)</h3>
      <Async state={status}>
        {(s) => (
          <p className="small" style={{ margin: '8px 0 12px' }}>
            {s.configured ? <>Configured: <b>{s.host}:{s.port}</b> from <b>{s.from_email}</b> · TLS {s.use_tls ? 'on' : 'off'} · password {s.password_set ? 'set' : 'not set'}</>
              : <span className="tone-danger">SMTP is not configured. Set SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD and SMTP_FROM_EMAIL on the server.</span>}
          </p>
        )}
      </Async>
      <div className="row">
        <label className="sr-only" htmlFor="smtp-to">Send test email to</label>
        <input id="smtp-to" className="input" style={{ maxWidth: 320 }} type="email" value={to} onChange={(e) => setTo(e.target.value)} />
        <button className="btn btn-secondary" disabled={busy || !to} onClick={send}>{busy ? 'Sending…' : 'Send Test Email'}</button>
      </div>
      {result && <p className={`alert ${result.ok ? 'alert-ok' : 'alert-danger'} small`} style={{ marginTop: 10 }} role="status">{result.text}</p>}
    </section>
  );
}

export default function Settings() {
  const { user, theme, setTheme, logout, toast, refreshMe } = useApp();
  const navigate = useNavigate();
  const state = useAsync(() => api.getSettings(), []);
  const [account, setAccount] = useState({ name: '', phone: '' });
  const [pw, setPw] = useState({ current_password: '', new_password: '', confirm: '' });
  const [msg, setMsg] = useState(null);
  const role = user?.role;

  useEffect(() => { if (state.data) setAccount({ name: state.data.account.name || '', phone: state.data.account.phone || '' }); }, [state.data]);

  const savePref = async (key, value) => {
    const prev = state.data;
    state.setData({ ...prev, preferences: { ...prev.preferences, [key]: value } });
    try { await api.updateSettings({ [key]: value }); }
    catch (e) { state.setData(prev); toast(`Couldn't save: ${e.message}`, 'danger'); }
  };
  const saveAccount = async (e) => {
    e.preventDefault(); setMsg(null);
    try { await api.updateAccount(account); toast('Account updated', 'ok'); refreshMe(); state.reload(); }
    catch (err) { setMsg({ ok: false, text: err.message }); }
  };
  const changePassword = async (e) => {
    e.preventDefault(); setMsg(null);
    if (pw.new_password !== pw.confirm) { setMsg({ ok: false, text: 'New passwords do not match.' }); return; }
    try { await api.changePassword({ current_password: pw.current_password, new_password: pw.new_password }); setPw({ current_password: '', new_password: '', confirm: '' }); setMsg({ ok: true, text: 'Password updated.' }); }
    catch (err) { setMsg({ ok: false, text: err.message }); }
  };
  const signOut = async () => { await logout(); navigate(LOGIN_PATH[role] || '/'); };

  return (
    <Async state={state} loadingLabel="Loading settings…" errorLabel="Failed to load settings">
      {(s) => (
        <div>
          <PageHeader title="Settings" subtitle="Preferences are saved to your account and follow you across devices." />
          {msg && <p className={`alert ${msg.ok ? 'alert-ok' : 'alert-danger'}`} role="status">{msg.text}</p>}

          <section className="card section" id="account" style={{ marginTop: 0 }}>
            <h3>Account</h3>
            <form onSubmit={saveAccount} className="form-grid" style={{ marginTop: 12 }}>
              <div className="field"><label className="field-label" htmlFor="s-name">Name</label><input id="s-name" className="input" value={account.name} onChange={(e) => setAccount({ ...account, name: e.target.value })} /></div>
              <div className="field"><label className="field-label" htmlFor="s-email">Email</label><input id="s-email" className="input" value={s.account.email || ''} disabled /></div>
              <div className="field"><label className="field-label" htmlFor="s-phone">Phone</label><input id="s-phone" className="input" value={account.phone} onChange={(e) => setAccount({ ...account, phone: e.target.value })} /></div>
              <div className="field" style={{ alignSelf: 'end' }}><button className="btn btn-primary">Save account</button></div>
            </form>
          </section>

          <section className="card section" id="security">
            <h3>Security</h3>
            <form onSubmit={changePassword} className="form-grid" style={{ marginTop: 12 }}>
              <div className="field"><label className="field-label" htmlFor="pw-c">Current password</label><input id="pw-c" type="password" className="input" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} required /></div>
              <div className="field"><label className="field-label" htmlFor="pw-n">New password</label><input id="pw-n" type="password" className="input" minLength={6} value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} required /></div>
              <div className="field"><label className="field-label" htmlFor="pw-r">Repeat new password</label><input id="pw-r" type="password" className="input" minLength={6} value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} required /></div>
              <div className="field" style={{ alignSelf: 'end' }}><button className="btn btn-secondary">Change password</button></div>
            </form>
          </section>

          <section className="card section" id="appearance">
            <h3>Appearance</h3>
            <div className="row" style={{ marginTop: 12 }} role="radiogroup" aria-label="Theme">
              {['light', 'dark'].map((t) => (
                <button key={t} role="radio" aria-checked={theme === t} className={`btn ${theme === t ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setTheme(t)}>{t === 'light' ? 'Light mode' : 'Dark mode'}</button>
              ))}
            </div>
          </section>

          <section className="card section" id="notifications">
            <h3>Notifications</h3>
            <div style={{ display: 'grid', gap: 4, marginTop: 8 }}>
              {NOTIFS.map(([key, label, hint]) => (
                <Toggle key={key} id={`n-${key}`} label={label} hint={hint} checked={s.preferences[key]}
                        disabled={key !== 'email_notifications' && !s.preferences.email_notifications} onChange={(v) => savePref(key, v)} />
              ))}
            </div>
            <p className="small muted" style={{ marginTop: 8 }}>In-app notifications (the bell) are always kept.</p>
          </section>

          {role === 'candidate' && (
            <section className="card section" id="privacy">
              <h3>Privacy</h3>
              <div className="form-grid" style={{ marginTop: 12 }}>
                <div className="field"><label className="field-label" htmlFor="pv-res">Resume visibility</label>
                  <select id="pv-res" className="input" value={s.preferences.resume_visibility} onChange={(e) => savePref('resume_visibility', e.target.value)}>
                    <option value="applied">Employers I apply to (after they unlock you)</option><option value="private">Only me — employers see scores and skills, not the file</option></select></div>
              </div>
              <Toggle id="pv-match" label="Use my data for job recommendations" checked={s.preferences.allow_data_for_matching} onChange={(v) => savePref('allow_data_for_matching', v)} />
            </section>
          )}

          {role === 'hr' && <SmtpTest defaultTo={s.account.email} />}

          <section className="card section" id="actions">
            <h3>Account actions</h3>
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn btn-secondary" onClick={signOut}>Log out</button>
            </div>
            <p className="small muted" style={{ marginTop: 10 }}>{s.delete_account.message}</p>
          </section>
        </div>
      )}
    </Async>
  );
}

export { SmtpTest };
