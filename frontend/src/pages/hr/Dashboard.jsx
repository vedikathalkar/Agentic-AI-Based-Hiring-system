import { useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../../api';
import { Async, EmptyState, PageHeader, StatCard, useAsync } from '../../components/ui';
import ProfileCompletion from '../../components/ProfileCompletion';
import StatusBadge from '../../components/StatusBadge';
import { formatScore, scoreTone, compareScoresDesc } from '../../utils/score';
import { applicationStageLabel, formatDate, pill, VERIFICATION_STATE } from '../../utils/status';

function VerificationBanner({ state }) {
  if (state === 'verified') return null;
  const text = {
    profile_incomplete: 'Complete your company profile and upload your documents to request verification.',
    verification_required: 'Your profile is ready — submit it for verification.',
    pending: 'Your company verification is under review. Posting jobs unlocks once it is approved.',
    rejected: 'Your verification needs changes. See the reason and resubmit.',
  }[state];
  return (
    <div className="banner">
      <p><b>{pill(VERIFICATION_STATE, state).text}.</b> <span className="muted">{text}</span></p>
      <Link className="btn btn-primary btn-sm" to="/hr/verification">{state === 'pending' ? 'View status' : 'Verify company'}</Link>
    </div>
  );
}

export default function HrDashboard() {
  const navigate = useNavigate();
  const dash = useAsync(() => api.hrDashboard(), []);
  const apps = useAsync(() => api.getCandidates(), []);
  const ranked = useMemo(() => [...(apps.data || [])]
    .sort((a, b) => compareScoresDesc(a.final_score, b.final_score) || compareScoresDesc(a.skill_score, b.skill_score)).slice(0, 8), [apps.data]);

  return (
    <Async state={dash} loadingLabel="Loading dashboard…" errorLabel="Failed to load dashboard">
      {(d) => {
        const s = d.stats;
        const funnel = [['Applied', s.total_applications], ['Assessed', s.assessed], ['Shortlisted', s.shortlisted],
          ['Interviews', s.scheduled_interviews], ['Offers sent', s.offers_sent], ['Hired', s.hired]];
        const max = Math.max(1, ...funnel.map((f) => f[1]));
        return (
          <>
            <PageHeader title="HR Dashboard" subtitle="Live overview of your roles, applicants and hiring pipeline."
                        actions={<button className="btn btn-primary" onClick={() => navigate('/hr/post-job')}>+ Post role</button>} />
            <VerificationBanner state={d.verification_state} />
            <div className="grid grid-stats">
              <StatCard label="Total jobs" value={s.total_jobs} hint={`${s.open_jobs} open`} to="/hr/jobs" />
              <StatCard label="Applications" value={s.total_applications} to="/hr/applications" />
              <StatCard label="Awaiting review" value={s.awaiting_review} tone="gold" to="/hr/applications" />
              <StatCard label="Assessed" value={s.assessed} to="/hr/assessments" />
              <StatCard label="Shortlisted" value={s.shortlisted} tone="ok" to="/hr/candidates" />
              <StatCard label="Upcoming interviews" value={s.scheduled_interviews} to="/hr/interviews" />
              <StatCard label="Offers sent" value={s.offers_sent} to="/hr/offers" />
              <StatCard label="Hired" value={s.hired} tone="ok" />
            </div>

            <div className="grid grid-2" style={{ marginTop: 16 }}>
              <section className="card section" style={{ marginTop: 0 }}>
                <h3>Hiring pipeline</h3>
                <div style={{ display: 'grid', gap: 10, marginTop: 12 }}>
                  {funnel.map(([label, value]) => (
                    <div key={label}>
                      <div className="row small" style={{ justifyContent: 'space-between' }}><span>{label}</span><b>{value}</b></div>
                      <div className="progress" role="progressbar" aria-label={`${label}: ${value}`} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value}>
                        <span className="bg-brand" style={{ width: `${(value / max) * 100}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              </section>
              <section className="card section" style={{ marginTop: 0 }}>
                <div className="row"><h3>Upcoming interviews</h3><span className="spacer" /><Link className="small" to="/hr/interviews">All</Link></div>
                {(d.upcoming_interviews || []).length === 0 ? <p className="small muted" style={{ marginTop: 10 }}>No interviews scheduled yet.</p> : (
                  <ul className="plain-list">{(d.upcoming_interviews || []).map((iv) => (
                    <li key={iv.schedule_id}><b>{iv.candidate_name}</b> · {iv.job_title}<br /><span className="small muted">{iv.date_label}, {iv.time_label} ({iv.timezone}) · {iv.mode}</span></li>
                  ))}</ul>
                )}
                <p className="small muted" style={{ marginTop: 12 }}>Credits balance: <b>{d.credits.toLocaleString()}</b> · <Link to="/hr/credits/buy">Buy credits</Link></p>
              </section>
            </div>

            {d.profile_completion.percent < 100 && <ProfileCompletion completion={d.profile_completion} basePath="/hr/company" title="Complete your company profile" />}

            <section className="card section">
              <div className="row" style={{ marginBottom: 8 }}><h3>Top candidates</h3><span className="spacer" /><Link className="btn btn-secondary btn-sm" to="/hr/applications">See all applications</Link></div>
              <Async state={apps} loadingLabel="Loading candidates…" errorLabel="Failed to load candidates">
                {() => ranked.length === 0 ? <EmptyState title="No applications yet">Share your open roles to start receiving applications.</EmptyState> : (
                  <div className="table-wrap">
                    <table className="table" style={{ minWidth: 640 }}>
                      <thead><tr><th scope="col">#</th><th scope="col">Candidate</th><th scope="col">Applied for</th><th scope="col">Final</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
                      <tbody>
                        {ranked.map((a, i) => (
                          <tr key={a.application_id}>
                            <td className="muted">{i + 1}</td>
                            <td><b>{a.candidate_name}</b><br /><span className="small muted">Applied {formatDate(a.applied_at)}</span></td>
                            <td>{a.job_title}</td>
                            <td className={`num tone-${scoreTone(a.final_score)}`}><b>{formatScore(a.final_score)}</b></td>
                            <td><StatusBadge label={applicationStageLabel(a)} /></td>
                            <td style={{ textAlign: 'right' }}><Link className="btn btn-secondary btn-sm" to={`/hr/candidate/${a.candidate_id}`}>View Candidate</Link></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Async>
            </section>
          </>
        );
      }}
    </Async>
  );
}
