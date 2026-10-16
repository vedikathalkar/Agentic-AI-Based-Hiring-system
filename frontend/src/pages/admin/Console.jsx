import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { useApp } from '../../context/AppContext';
import { Async, EmptyState, Modal, PageHeader, StatCard, Tabs, money, useAsync } from '../../components/ui';
import TicketThread, { TICKET_STATUS } from '../../components/TicketThread';
import { SmtpTest } from '../shared/Settings';
import { formatDate, pill, VERIFICATION_STATE } from '../../utils/status';

const yes = (v) => (v ? <span className="tone-ok">Yes</span> : <span className="tone-danger">No</span>);

export function AdminOverview() {
  const state = useAsync(() => api.adminOverview(), []);
  return (
    <Async state={state} loadingLabel="Loading overview…" errorLabel="Failed to load overview">
      {({ counts: c, credits, system: s }) => (
        <>
          <PageHeader title="Admin overview" subtitle="Platform activity and system health." />
          <div className="grid grid-stats">
            <StatCard label="Pending verifications" value={c.pending_verifications} tone="gold" to="/admin/verifications" />
            <StatCard label="Verified companies" value={c.verified_companies} tone="ok" />
            <StatCard label="HR accounts" value={c.hr_accounts} to="/admin/users" />
            <StatCard label="Candidates" value={c.candidate_accounts} to="/admin/users" />
            <StatCard label="Jobs" value={c.jobs} to="/admin/jobs" />
            <StatCard label="Applications" value={c.applications} />
            <StatCard label="Open tickets" value={c.open_tickets} tone="gold" to="/admin/support" />
            <StatCard label="Failed emails" value={c.failed_emails} tone={c.failed_emails ? 'danger' : 'ok'} to="/admin/emails" />
            <StatCard label="Upcoming interviews" value={c.upcoming_interviews} />
            <StatCard label="Offers sent" value={c.offers_sent} />
            <StatCard label="Credits issued / spent" value={`${credits.issued.toLocaleString()} / ${credits.spent.toLocaleString()}`} />
            <StatCard label="Revenue" value={money(credits.revenue_paise)} tone="ok" />
          </div>
          <section className="card section">
            <h3>System</h3>
            <dl className="kv" style={{ marginTop: 10 }}>
              <dt>SMTP configured</dt><dd>{yes(s.smtp.configured)}{s.smtp.host ? ` · ${s.smtp.host}:${s.smtp.port}` : ''}</dd>
              <dt>Payments (Razorpay)</dt><dd>{yes(s.payments_configured)}</dd>
              <dt>GROQ API key</dt><dd>{yes(s.groq_api_key_configured)}</dd>
              <dt>Scheduler</dt><dd>{s.scheduler.running ? `Running every ${s.scheduler.interval_seconds}s` : 'Not running'}{s.scheduler.last_run ? ` · last run ${new Date(s.scheduler.last_run * 1000).toLocaleString()}` : ''}</dd>
              <dt>Code sandbox</dt><dd>{s.sandbox.mode} · network isolated {yes(s.sandbox.network_isolated)} · production ready {yes(s.sandbox.production_ready)} · {s.languages.join(', ') || 'no languages'}</dd>
            </dl>
            <Link className="btn btn-secondary btn-sm" style={{ marginTop: 12 }} to="/admin/system">Open system tools</Link>
          </section>
        </>
      )}
    </Async>
  );
}

export function AdminVerifications() {
  const { toast } = useApp();
  const [status, setStatus] = useState('pending');
  const list = useAsync(() => api.adminVerifications(status), [status]);
  const [rejecting, setRejecting] = useState(null);
  const [reason, setReason] = useState('');
  const act = async (fn, msg) => { try { await fn(); toast(msg, 'ok'); list.reload(); } catch (e) { toast(e.message, 'danger'); } };
  return (
    <>
      <PageHeader title="Company verifications" subtitle="Review company details and documents, then approve or send back with a reason." />
      <Tabs tabs={[['pending', 'Pending'], ['verified', 'Verified'], ['rejected', 'Rejected'], ['unverified', 'Not submitted'], ['all', 'All']]} value={status} onChange={setStatus} />
      <Async state={list} loadingLabel="Loading…" errorLabel="Failed to load verifications">
        {(rows) => rows.length === 0 ? <EmptyState title="Nothing here" /> : (
          <div style={{ display: 'grid', gap: 12 }}>
            {rows.map((c) => {
              const p = pill(VERIFICATION_STATE, c.verification_status);
              return (
                <article key={c.company_id} className="card section" style={{ marginTop: 0 }}>
                  <div className="row"><h3>{c.name || 'Unnamed company'}</h3><span className={`pill ${p.cls}`}>{p.text}</span><span className="spacer" />
                    <span className="small muted">Profile {c.completion ?? '—'}% · submitted {formatDate(c.submitted_at, true)}</span></div>
                  <div className="grid grid-2" style={{ marginTop: 10 }}>
                    <dl className="kv">
                      <dt>Website</dt><dd>{c.website ? <a href={c.website} target="_blank" rel="noreferrer">{c.website}</a> : '—'}</dd>
                      <dt>Official email</dt><dd>{c.official_email || '—'}</dd>
                      <dt>Industry / size</dt><dd>{c.industry || '—'} · {c.company_size || '—'}</dd>
                      <dt>Headquarters</dt><dd>{c.headquarters || '—'}</dd>
                      <dt>Registration / GST</dt><dd>{c.registration_number || '—'} · {c.gst_number || '—'}</dd>
                    </dl>
                    <dl className="kv">
                      <dt>HR</dt><dd>{c.hr ? `${c.hr.name} (${c.hr.email})` : '—'}</dd>
                      <dt>Designation</dt><dd>{c.hr?.designation || '—'}</dd>
                      <dt>Phone</dt><dd>{c.hr?.phone || '—'}</dd>
                      <dt>Documents</dt><dd>{c.documents.length === 0 ? 'None' : c.documents.map((d) => (
                        <button key={d.document_id} className="link-btn" style={{ marginRight: 10 }} onClick={() => api.openCompanyDocument(d.document_id).catch((e) => toast(e.message, 'danger'))}>{d.doc_type.replace('_', ' ')}</button>))}</dd>
                    </dl>
                  </div>
                  {c.description && <p className="small muted" style={{ marginTop: 8 }}>{c.description}</p>}
                  {c.rejection_reason && <p className="alert alert-warn small" style={{ marginTop: 8 }}>Previous rejection: {c.rejection_reason}</p>}
                  {c.verification_status === 'pending' && (
                    <div className="row" style={{ marginTop: 12 }}>
                      <button className="btn btn-ok" onClick={() => act(() => api.adminApprove(c.company_id), `${c.name} verified`)}>Approve</button>
                      <button className="btn btn-danger" onClick={() => { setRejecting(c); setReason(''); }}>Reject</button>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </Async>
      {rejecting && (
        <Modal title={`Reject ${rejecting.name}?`} onClose={() => setRejecting(null)}
               footer={<><button className="btn btn-secondary" onClick={() => setRejecting(null)}>Cancel</button>
                 <button className="btn btn-danger" disabled={reason.trim().length < 5} onClick={async () => { await act(() => api.adminReject(rejecting.company_id, reason), 'Sent back for correction'); setRejecting(null); }}>Reject</button></>}>
          <label className="field-label" htmlFor="rj">Reason (shown to the HR user, min 5 characters)</label>
          <textarea id="rj" className="input" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Modal>
      )}
    </>
  );
}

export function AdminUsers() {
  const { toast } = useApp();
  const [role, setRole] = useState('hr');
  const [q, setQ] = useState('');
  const list = useAsync(() => api.adminUsers(role, q), [role, q]);
  const [adjust, setAdjust] = useState(null);
  const save = async () => {
    try { const r = await api.adminAdjustCredits({ role, account_id: adjust.account_id, amount: Number(adjust.amount), reason: adjust.reason }); toast(`Balance is now ${r.balance}`, 'ok'); setAdjust(null); list.reload(); }
    catch (e) { toast(e.message, 'danger'); }
  };
  return (
    <>
      <PageHeader title="Users & credits" subtitle="All accounts. Credit adjustments are written to the ledger and notified to the user." />
      <Tabs tabs={[['hr', 'HR accounts'], ['candidate', 'Candidates']]} value={role} onChange={setRole} />
      <div className="tools"><label className="sr-only" htmlFor="uq">Search</label><input id="uq" className="input" placeholder="Search name or email…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      <Async state={list} loadingLabel="Loading users…" errorLabel="Failed to load users">
        {(rows) => rows.length === 0 ? <EmptyState title="No users found" /> : (
          <div className="card table-wrap"><table className="table">
            <thead><tr><th scope="col">Name</th><th scope="col">Email</th>{role === 'hr' ? <><th scope="col">Company</th><th scope="col">Verification</th><th scope="col">Jobs</th></> : <th scope="col">Applications</th>}<th scope="col">Credits</th><th scope="col">Joined</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{rows.map((u) => (
              <tr key={u.account_id}><td><b>{u.name}</b></td><td>{u.email}</td>
                {role === 'hr' ? <><td>{u.company}</td><td><span className={`pill ${pill(VERIFICATION_STATE, u.verification_status).cls}`}>{pill(VERIFICATION_STATE, u.verification_status).text}</span></td><td>{u.jobs}</td></> : <td>{u.applications}</td>}
                <td className="num">{u.credits.toLocaleString()}</td><td>{formatDate(u.created_at)}</td>
                <td><button className="btn btn-secondary btn-sm" onClick={() => setAdjust({ ...u, amount: 100, reason: '' })}>Adjust credits</button></td></tr>
            ))}</tbody>
          </table></div>
        )}
      </Async>
      {adjust && (
        <Modal title={`Adjust credits — ${adjust.name}`} onClose={() => setAdjust(null)}
               footer={<><button className="btn btn-secondary" onClick={() => setAdjust(null)}>Cancel</button><button className="btn btn-primary" disabled={!Number(adjust.amount) || adjust.reason.trim().length < 3} onClick={save}>Save</button></>}>
          <p className="small muted">Current balance: {adjust.credits}. Use a negative number to remove credits.</p>
          <div className="field"><label className="field-label" htmlFor="adj-a">Amount</label><input id="adj-a" type="number" className="input" value={adjust.amount} onChange={(e) => setAdjust({ ...adjust, amount: e.target.value })} /></div>
          <div className="field"><label className="field-label" htmlFor="adj-r">Reason</label><input id="adj-r" className="input" value={adjust.reason} onChange={(e) => setAdjust({ ...adjust, reason: e.target.value })} /></div>
        </Modal>
      )}
    </>
  );
}

export function AdminJobs() {
  const { toast } = useApp();
  const jobs = useAsync(() => api.adminJobs(), []);
  const hrs = useAsync(() => api.adminUsers('hr'), []);
  const assign = async (jobId, hrId) => { if (!hrId) return; try { await api.adminAssignJob(jobId, Number(hrId)); toast('Owner assigned', 'ok'); jobs.reload(); } catch (e) { toast(e.message, 'danger'); } };
  return (
    <>
      <PageHeader title="Jobs" subtitle="All roles. Legacy roles without an owner are visible to every HR account — assign them to scope access." />
      <Async state={jobs} loadingLabel="Loading jobs…" errorLabel="Failed to load jobs">
        {(rows) => rows.length === 0 ? <EmptyState title="No jobs yet" /> : (
          <div className="card table-wrap"><table className="table" style={{ minWidth: 640 }}>
            <thead><tr><th scope="col">Job</th><th scope="col">Status</th><th scope="col">Applications</th><th scope="col">Owner</th></tr></thead>
            <tbody>{rows.map((j) => (
              <tr key={j.job_id}><td><b>{j.title}</b><br /><span className="small muted">#{j.job_id} · {formatDate(j.created_at)}</span></td><td>{j.status}</td><td>{j.applications}</td>
                <td>{j.owner ? `${j.owner.name} · ${j.owner.company}` : (
                  <select className="input" aria-label={`Assign owner for ${j.title}`} defaultValue="" onChange={(e) => assign(j.job_id, e.target.value)}>
                    <option value="">Unowned — assign…</option>{(hrs.data || []).map((h) => <option key={h.account_id} value={h.account_id}>{h.name} ({h.company})</option>)}
                  </select>)}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </Async>
    </>
  );
}

export function AdminSupport() {
  const [status, setStatus] = useState('');
  const list = useAsync(() => api.getTickets(status || undefined), [status]);
  const [selected, setSelected] = useState(null);
  const open = async (id) => { try { setSelected(await api.getTicket(id)); } catch { setSelected(null); } };
  return (
    <>
      <PageHeader title="Support tickets" subtitle="Tickets from candidates and HR users. Replies are emailed and notified to the requester." />
      <Tabs tabs={[['', 'All'], ['open', 'Open'], ['in_progress', 'In progress'], ['resolved', 'Resolved'], ['closed', 'Closed']]} value={status} onChange={setStatus} />
      <div className="grid support-grid">
        <section className="card" style={{ padding: 12 }}>
          <Async state={list} loadingLabel="Loading tickets…" errorLabel="Failed to load tickets">
            {(rows) => rows.length === 0 ? <EmptyState title="No tickets" /> : (
              <ul className="plain-list" style={{ marginTop: 0 }}>{rows.map((t) => {
                const [label, cls] = TICKET_STATUS[t.status] || [t.status, 'pill-neutral'];
                return (
                  <li key={t.ticket_id}><button className="notif-item" style={{ borderRadius: 8, border: selected?.ticket_id === t.ticket_id ? '1px solid var(--brand)' : undefined }} onClick={() => open(t.ticket_id)}>
                    <b>#{t.ticket_id} {t.subject}</b>
                    <span className="row small"><span className={`pill ${cls}`}>{label}</span><span className="muted">{t.requester_role} · {t.category} · {formatDate(t.updated_at)}</span></span>
                  </button></li>
                );
              })}</ul>
            )}
          </Async>
        </section>
        <section className="card section" style={{ marginTop: 0 }}>
          {selected ? <TicketThread admin ticket={selected} onChange={(t) => { setSelected(t); list.reload(); }} /> : <p className="muted">Select a ticket.</p>}
        </section>
      </div>
    </>
  );
}

export function AdminEmails() {
  const { toast } = useApp();
  const [status, setStatus] = useState('');
  const list = useAsync(() => api.emailLogs({ status: status || undefined, limit: 200 }), [status]);
  const retry = async (id) => { try { const r = await api.retryEmail(id); toast(r.status === 'sent' ? 'Email sent' : `Still failing: ${r.error}`, r.status === 'sent' ? 'ok' : 'danger'); list.reload(); } catch (e) { toast(e.message, 'danger'); } };
  return (
    <>
      <PageHeader title="Email log" subtitle="Every email the platform queued. Failed emails can be retried once SMTP is working." />
      <Tabs tabs={[['', 'All'], ['failed', 'Failed'], ['queued', 'Queued'], ['sent', 'Sent']]} value={status} onChange={setStatus} />
      <Async state={list} loadingLabel="Loading emails…" errorLabel="Failed to load email log">
        {(rows) => rows.length === 0 ? <EmptyState title="No emails" /> : (
          <div className="card table-wrap"><table className="table">
            <thead><tr><th scope="col">When</th><th scope="col">To</th><th scope="col">Subject</th><th scope="col">Status</th><th scope="col">Attempts</th><th scope="col"><span className="sr-only">Retry</span></th></tr></thead>
            <tbody>{rows.map((e) => (
              <tr key={e.email_id}><td className="small">{formatDate(e.created_at, true)}</td><td>{e.to}</td>
                <td>{e.subject}<br /><span className="small muted">{e.template}{e.related_type ? ` · ${e.related_type} #${e.related_id}` : ''}</span>{e.error && <><br /><span className="small tone-danger">{e.error}</span></>}</td>
                <td><span className={`pill ${e.status === 'sent' ? 'pill-ok' : e.status === 'failed' ? 'pill-danger' : 'pill-neutral'}`}>{e.status}</span></td>
                <td>{e.attempts}</td><td>{e.status !== 'sent' && <button className="btn btn-secondary btn-sm" onClick={() => retry(e.email_id)}>Retry</button>}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </Async>
    </>
  );
}

export function AdminSystem() {
  const { toast } = useApp();
  const health = useAsync(() => api.getHealth(), []);
  const [run, setRun] = useState(null);
  const [busy, setBusy] = useState(false);
  const runNow = async () => { setBusy(true); try { setRun(await api.adminRunScheduler()); toast('Scheduled jobs ran', 'ok'); } catch (e) { toast(e.message, 'danger'); } finally { setBusy(false); } };
  return (
    <div>
      <PageHeader title="System" subtitle="Health, background jobs and email delivery." />
      <section className="card section" style={{ marginTop: 0 }}>
        <h3>Health</h3>
        <Async state={health} loadingLabel="Checking…">{(h) => <pre className="pre" style={{ marginTop: 10 }}>{JSON.stringify(h, null, 2)}</pre>}</Async>
      </section>
      <section className="card section">
        <h3>Scheduled jobs</h3>
        <p className="small muted" style={{ margin: '8px 0 12px' }}>Interview reminders (one day before), auto-submitting expired assessments, expiring offers and retrying failed emails. They run automatically; use this to run them now.</p>
        <button className="btn btn-primary" disabled={busy} onClick={runNow}>{busy ? 'Running…' : 'Run due jobs now'}</button>
        {run && <pre className="pre" style={{ marginTop: 10 }}>{JSON.stringify(run, null, 2)}</pre>}
      </section>
      <SmtpTest defaultTo="" />
    </div>
  );
}
