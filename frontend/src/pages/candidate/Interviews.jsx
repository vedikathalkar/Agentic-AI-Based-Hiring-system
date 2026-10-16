import { useState } from 'react';
import { api } from '../../api';
import { Async, EmptyState, PageHeader, Tabs, useAsync } from '../../components/ui';
import { INTERVIEW_STATUS, pill } from '../../utils/status';

export default function CandidateInterviews() {
  const [tab, setTab] = useState('upcoming');
  const state = useAsync(() => api.getInterviews(tab === 'upcoming' ? 'upcoming' : undefined), [tab]);
  return (
    <>
      <PageHeader title="Interviews" subtitle="Times are shown in the interview's timezone. You get an email when an interview is scheduled and a reminder one day before." />
      <Tabs tabs={[['upcoming', 'Upcoming'], ['all', 'All interviews']]} value={tab} onChange={setTab} />
      <Async state={state} loadingLabel="Loading interviews…" errorLabel="Failed to load interviews">
        {(rows) => rows.length === 0 ? <EmptyState title="No interviews scheduled yet">When an employer schedules an interview it appears here.</EmptyState> : (
          <div style={{ display: 'grid', gap: 12 }}>
            {rows.map((iv) => {
              const p = pill(INTERVIEW_STATUS, iv.status);
              return (
                <article key={iv.schedule_id} className="card section" style={{ marginTop: 0 }}>
                  <div className="row"><h3>{iv.job_title}</h3><span className={`pill ${p.cls}`}>{p.text}</span></div>
                  <p className="small muted">{iv.company_name}</p>
                  <dl className="kv" style={{ marginTop: 10 }}>
                    <dt>When</dt><dd>{iv.date_label}, {iv.time_label} ({iv.timezone})</dd>
                    <dt>Duration</dt><dd>{iv.duration_minutes} minutes</dd>
                    <dt>Mode</dt><dd>{iv.mode}</dd>
                    {iv.meeting_link && (<><dt>Meeting link</dt><dd><a href={iv.meeting_link} target="_blank" rel="noreferrer">{iv.meeting_link}</a></dd></>)}
                    {iv.location && (<><dt>Location</dt><dd>{iv.location}</dd></>)}
                    {iv.interviewer && (<><dt>Interviewer</dt><dd>{iv.interviewer}</dd></>)}
                  </dl>
                </article>
              );
            })}
          </div>
        )}
      </Async>
    </>
  );
}
