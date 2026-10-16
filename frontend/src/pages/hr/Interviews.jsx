import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../../api';
import { useApp } from '../../context/AppContext';
import { Async, EmptyState, Modal, PageHeader, Tabs, useAsync } from '../../components/ui';
import { INTERVIEW_STATUS, pill } from '../../utils/status';

const today = () => new Date().toISOString().slice(0, 10);
const BLANK = { date: '', time: '11:00', timezone: 'Asia/Kolkata', duration_minutes: 45, mode: 'Google Meet', meeting_link: '', location: '', interviewer: '', notes: '' };

function InterviewFields({ form, setForm, options, idp }) {
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  return (
    <div className="form-grid">
      <div className="field"><label className="field-label" htmlFor={`${idp}-date`}>Date</label><input id={`${idp}-date`} type="date" min={today()} className="input" value={form.date} onChange={set('date')} required /></div>
      <div className="field"><label className="field-label" htmlFor={`${idp}-time`}>Time</label><input id={`${idp}-time`} type="time" className="input" value={form.time} onChange={set('time')} required /></div>
      <div className="field"><label className="field-label" htmlFor={`${idp}-tz`}>Timezone</label>
        <select id={`${idp}-tz`} className="input" value={form.timezone} onChange={set('timezone')}>{(options?.timezones || ['Asia/Kolkata']).map((t) => <option key={t}>{t}</option>)}</select></div>
      <div className="field"><label className="field-label" htmlFor={`${idp}-dur`}>Duration (minutes)</label><input id={`${idp}-dur`} type="number" min={10} max={480} className="input" value={form.duration_minutes} onChange={set('duration_minutes')} /></div>
      <div className="field"><label className="field-label" htmlFor={`${idp}-mode`}>Mode</label>
        <select id={`${idp}-mode`} className="input" value={form.mode} onChange={set('mode')}>{(options?.modes || ['Google Meet']).map((m) => <option key={m}>{m}</option>)}</select></div>
      {form.mode === 'On-site'
        ? <div className="field"><label className="field-label" htmlFor={`${idp}-loc`}>Location / address</label><input id={`${idp}-loc`} className="input" value={form.location || ''} onChange={set('location')} /></div>
        : <div className="field"><label className="field-label" htmlFor={`${idp}-link`}>Meeting link</label><input id={`${idp}-link`} className="input" placeholder="https://" value={form.meeting_link || ''} onChange={set('meeting_link')} /></div>}
      <div className="field"><label className="field-label" htmlFor={`${idp}-iv`}>Interviewer</label><input id={`${idp}-iv`} className="input" value={form.interviewer || ''} onChange={set('interviewer')} /></div>
      <div className="field" style={{ gridColumn: '1 / -1' }}><label className="field-label" htmlFor={`${idp}-notes`}>Notes (internal)</label><textarea id={`${idp}-notes`} className="input" rows={2} value={form.notes || ''} onChange={set('notes')} /></div>
    </div>
  );
}

export default function HrInterviews() {
  const { toast } = useApp();
  const [params] = useSearchParams();
  const [tab, setTab] = useState('upcoming');
  const list = useAsync(() => api.getInterviews(tab === 'upcoming' ? 'upcoming' : undefined), [tab]);
  const apps = useAsync(() => api.getCandidates(), []);
  const options = useAsync(() => api.interviewOptions(), []);
  const [form, setForm] = useState({ ...BLANK, application_id: params.get('application') || '' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null);
  const [cancelling, setCancelling] = useState(null);
  const [reason, setReason] = useState('');

  const schedulable = useMemo(() => (apps.data || []).filter((a) => !['rejected', 'hired', 'offer_declined'].includes(a.status)), [apps.data]);

  const book = async (e) => {
    e.preventDefault();
    setSaving(true); setError(null);
    try {
      await api.createInterview({ ...form, application_id: Number(form.application_id), duration_minutes: Number(form.duration_minutes) });
      toast('Interview scheduled — confirmation emails are on their way', 'ok');
      setForm({ ...BLANK, application_id: '' });
      list.reload(); apps.reload();
    } catch (err) { setError(err.message); }
    finally { setSaving(false); }
  };
  const act = async (fn, msg) => {
    try { await fn(); toast(msg, 'ok'); list.reload(); } catch (err) { toast(err.message, 'danger'); }
  };
  const saveEdit = async () => {
    const { schedule_id: id, ...rest } = editing;
    await act(() => api.updateInterview(id, { date: rest.date, time: rest.time, timezone: rest.timezone, duration_minutes: Number(rest.duration_minutes),
      mode: rest.mode, meeting_link: rest.meeting_link, location: rest.location, interviewer: rest.interviewer, notes: rest.notes }), 'Interview updated');
    setEditing(null);
  };

  return (
    <>
      <PageHeader title="Interviews" subtitle="Scheduling emails the candidate and you as soon as the interview is saved. Reminders go out automatically one day before." />
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', alignItems: 'start' }}>
        <section className="card section" style={{ marginTop: 0 }}>
          <Tabs tabs={[['upcoming', 'Upcoming'], ['all', 'All']]} value={tab} onChange={setTab} />
          <Async state={list} loadingLabel="Loading interviews…" errorLabel="Failed to load interviews">
            {(rows) => rows.length === 0 ? <EmptyState title="No interviews scheduled yet">Book a slot using the form.</EmptyState> : (
              <ul className="plain-list" style={{ marginTop: 0 }}>
                {rows.map((iv) => {
                  const p = pill(INTERVIEW_STATUS, iv.status);
                  const active = ['scheduled', 'confirmed', 'rescheduled'].includes(iv.status);
                  return (
                    <li key={iv.schedule_id}>
                      <div className="row"><Link to={`/hr/candidate/${iv.candidate_id}`}><b>{iv.candidate_name}</b></Link><span className="small muted">· {iv.job_title}</span><span className="spacer" /><span className={`pill ${p.cls}`}>{p.text}</span></div>
                      <p className="small">{iv.date_label}, {iv.time_label} ({iv.timezone}) · {iv.duration_minutes} min · {iv.mode}{iv.interviewer ? ` · ${iv.interviewer}` : ''}</p>
                      {iv.meeting_link && <p className="small"><a href={iv.meeting_link} target="_blank" rel="noreferrer">{iv.meeting_link}</a></p>}
                      <p className="small muted">Reminder: {iv.reminder_status === 'sent' ? 'sent' : iv.reminder_status === 'skipped' ? 'not needed (less than a day away)' : iv.reminder_status || 'pending'}</p>
                      {active && (
                        <div className="row" style={{ marginTop: 6 }}>
                          {iv.status !== 'confirmed' && <button className="btn btn-secondary btn-sm" onClick={() => act(() => api.updateInterview(iv.schedule_id, { status: 'confirmed' }), 'Marked confirmed')}>Confirm</button>}
                          <button className="btn btn-secondary btn-sm" onClick={() => setEditing({ ...iv })}>Reschedule / edit</button>
                          <button className="btn btn-ok btn-sm" onClick={() => act(() => api.updateInterview(iv.schedule_id, { status: 'completed' }), 'Marked completed')}>Completed</button>
                          <button className="btn btn-secondary btn-sm" onClick={() => act(() => api.resendInterview(iv.schedule_id), 'Confirmation re-sent')}>Resend email</button>
                          <button className="btn btn-danger btn-sm" onClick={() => { setCancelling(iv); setReason(''); }}>Cancel</button>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </Async>
        </section>
        <section className="card section" style={{ marginTop: 0 }}>
          <h3 style={{ marginBottom: 12 }}>Book an interview</h3>
          <form onSubmit={book}>
            <div className="field"><label className="field-label" htmlFor="bk-app">Candidate / application</label>
              <select id="bk-app" className="input" value={form.application_id} onChange={(e) => setForm({ ...form, application_id: e.target.value })} required>
                <option value="">Select a candidate…</option>
                {schedulable.map((a) => <option key={a.application_id} value={a.application_id}>{a.candidate_name} — {a.job_title} ({a.status})</option>)}
              </select></div>
            <InterviewFields form={form} setForm={setForm} options={options.data} idp="bk" />
            {error && <p className="alert alert-danger small" role="alert">{error}</p>}
            <button className="btn btn-primary btn-block" disabled={saving || !form.application_id || !form.date}>{saving ? 'Saving…' : 'Confirm and notify'}</button>
          </form>
        </section>
      </div>
      {editing && (
        <Modal wide title={`Edit interview — ${editing.candidate_name}`} onClose={() => setEditing(null)}
               footer={<><button className="btn btn-secondary" onClick={() => setEditing(null)}>Close</button><button className="btn btn-primary" onClick={saveEdit}>Save changes</button></>}>
          <p className="small muted" style={{ marginBottom: 10 }}>Changing the date, time or timezone marks the interview as rescheduled, emails both parties and resets the reminder.</p>
          <InterviewFields form={editing} setForm={setEditing} options={options.data} idp="ed" />
        </Modal>
      )}
      {cancelling && (
        <Modal title={`Cancel interview with ${cancelling.candidate_name}?`} onClose={() => setCancelling(null)}
               footer={<><button className="btn btn-secondary" onClick={() => setCancelling(null)}>Keep</button>
                 <button className="btn btn-danger" onClick={async () => { await act(() => api.cancelInterview(cancelling.schedule_id, reason), 'Interview cancelled'); setCancelling(null); }}>Cancel interview</button></>}>
          <label className="field-label" htmlFor="cx-reason">Reason (sent to the candidate)</label>
          <textarea id="cx-reason" className="input" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Modal>
      )}
    </>
  );
}
