import { Link } from 'react-router-dom';
import { api } from '../../api';
import { Async, EmptyState, PageHeader, StatCard, useAsync } from '../../components/ui';
import ProfileCompletion from '../../components/ProfileCompletion';
import DashboardSearch from '../../components/DashboardSearch';
import HiringPipeline from '../../components/HiringPipeline';
import StatusBadge from '../../components/StatusBadge';
import { formatScore } from '../../utils/score';
import { applicationStageLabel, formatDate, OFFER_STATUS, pill } from '../../utils/status';

const STAGE_LABEL = { applied: 'Applied', skill: 'Skill evaluation', experience: 'Experience evaluation', assessment: 'Assessment',
  interview: 'Interview', offer: 'Offer letter', hired: 'Hired' };

export default function CandidateDashboard() {
  const state = useAsync(() => api.candidateDashboard(), []);
  return (
    <Async state={state} loadingLabel="Loading your dashboard…" errorLabel="Failed to load your dashboard">
      {(d) => (
        <>
          <PageHeader title={`Welcome back, ${d.name?.split(' ')[0] || ''}`} subtitle="Everything about your applications in one place."
                      actions={<Link className="btn btn-primary" to="/jobs">Find jobs</Link>} />
          <div className="grid grid-stats">
            <StatCard label="Applications" value={d.stats.applications} to="/applications" />
            <StatCard label="Assessments pending" value={d.stats.assessments_pending} tone="gold" to="/assessments" />
            <StatCard label="Assessments completed" value={d.stats.assessments_completed} tone="ok" to="/assessments" />
            <StatCard label="Upcoming interviews" value={d.stats.upcoming_interviews} to="/interviews" />
            <StatCard label="Offers" value={d.stats.offers} tone="ok" to="/offers" />
            <StatCard label="Profile completion" value={`${d.profile_completion.percent}%`} tone={d.profile_completion.percent === 100 ? 'ok' : 'gold'} to="/profile" />
          </div>

          <DashboardSearch />

          <section className="card section" aria-label="Your hiring pipeline">
            <h3 style={{ marginBottom: 12 }}>Your pipeline</h3>
            <div className="pipeline-steps">
              {(d.pipeline || []).map((p) => (
                <div key={p.stage} className={`pipeline-step${p.count ? ' on' : ''}`}><b>{p.count}</b><span className="small">{STAGE_LABEL[p.stage] || p.label}</span></div>
              ))}
              <div className={`pipeline-step${d.stopped_count ? ' stopped' : ''}`}><b>{d.stopped_count || 0}</b><span className="small">Stopped</span></div>
            </div>
            <p className="small muted" style={{ marginTop: 10 }}>{d.stats.shortlisted} shortlisted · {d.stats.rejected} not selected</p>
            {(d.applications || []).slice(0, 3).map((a) => (
              <div key={a.application_id} style={{ marginTop: 18 }}>
                <div className="row" style={{ marginBottom: 10 }}><b>{a.job_title}</b><span className="spacer" /><Link className="small" to="/applications">{a.pipeline?.outcome?.state === 'stopped' ? 'Why?' : 'Details'}</Link></div>
                <HiringPipeline pipeline={a.pipeline} compact />
              </div>
            ))}
          </section>

          <div className="grid grid-2" style={{ marginTop: 16 }}>
            <ProfileCompletion completion={d.profile_completion} compact={d.profile_completion.percent === 100} />
            <section className="card section" style={{ marginTop: 16 }}>
              <h3>Resume</h3>
              {d.resume.uploaded
                ? <p className="small" style={{ marginTop: 8 }}>✓ <b>{d.resume.file_name}</b> · uploaded {formatDate(d.resume.uploaded_at)}</p>
                : <p className="small muted" style={{ marginTop: 8 }}>No resume on your profile yet.</p>}
              <div className="row" style={{ marginTop: 12 }}>
                <Link className="btn btn-secondary btn-sm" to="/profile#resume">{d.resume.uploaded ? 'Replace resume' : 'Upload resume'}</Link>
                <Link className="btn btn-secondary btn-sm" to="/ats">Check ATS score</Link>
              </div>
            </section>
          </div>

          <div className="grid grid-2" style={{ marginTop: 16 }}>
            <section className="card section">
              <div className="row"><h3>Pending assessments</h3><span className="spacer" /><Link className="small" to="/assessments">All</Link></div>
              {(d.pending_assessments || []).length === 0 ? <p className="small muted" style={{ marginTop: 10 }}>No pending assessments.</p> : (
                <ul className="plain-list">
                  {(d.pending_assessments || []).map((a) => (
                    <li key={a.application_id} className="row">
                      <span>{a.job_title}</span><span className="spacer" />
                      <Link className="btn btn-primary btn-sm" to={`/assessment?application=${a.application_id}`}>
                        {a.assessment_status === 'in_progress' ? 'Continue' : 'Take Assessment'}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section className="card section">
              <div className="row"><h3>Upcoming interviews</h3><span className="spacer" /><Link className="small" to="/interviews">All</Link></div>
              {(d.interviews || []).length === 0 ? <p className="small muted" style={{ marginTop: 10 }}>No interviews scheduled yet.</p> : (
                <ul className="plain-list">
                  {(d.interviews || []).map((iv) => (
                    <li key={iv.schedule_id}>
                      <b>{iv.job_title}</b> · {iv.company_name}<br />
                      <span className="small muted">{iv.date_label}, {iv.time_label} ({iv.timezone}) · {iv.mode}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>

          {(d.offers || []).length > 0 && (
            <section className="card section">
              <h3>Offers</h3>
              <ul className="plain-list">
                {(d.offers || []).map((o) => {
                  const p = pill(OFFER_STATUS, o.status);
                  return (
                    <li key={o.offer_id} className="row">
                      <span>{o.job_title}</span><span className={`pill ${p.cls}`}>{p.text}</span><span className="spacer" />
                      <Link className="btn btn-secondary btn-sm" to={`/offers/${o.offer_id}`}>View offer</Link>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          <section className="card section">
            <div className="row"><h3>Your applications</h3><span className="spacer" /><Link className="small" to="/applications">All</Link></div>
            {(d.applications || []).length === 0 ? <EmptyState title="No applications yet" action={<Link className="btn btn-primary btn-sm" to="/jobs">Browse jobs</Link>}>Apply to a role to see your progress here.</EmptyState> : (
              <div className="table-wrap">
                <table className="table" style={{ minWidth: 560 }}>
                  <thead><tr><th scope="col">Role</th><th scope="col">Applied</th><th scope="col">Skill</th><th scope="col">Test</th><th scope="col">Status</th></tr></thead>
                  <tbody>
                    {(d.applications || []).map((a) => (
                      <tr key={a.application_id}>
                        <td><b>{a.job_title}</b></td><td>{formatDate(a.applied_at)}</td>
                        <td>{formatScore(a.skill_score)}</td>
                        <td>{a.assessment_status === 'completed' ? formatScore(a.test_score) : '—'}</td>
                        <td><StatusBadge label={applicationStageLabel(a)} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="card section">
            <h3>Recommended jobs</h3>
            {(d.recommended_jobs || []).length === 0 ? <p className="small muted" style={{ marginTop: 8 }}>No open roles you haven't applied to yet.</p> : (
              <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', marginTop: 12 }}>
                {(d.recommended_jobs || []).map((j) => (
                  <div key={j.job_id} className="list-card">
                    <b>{j.title}</b>
                    <p className="small muted">{[j.team, j.location].filter(Boolean).join(' · ') || 'Hirelune'}</p>
                    <p className="small" style={{ margin: '6px 0' }}>
                      {j.match === null ? 'Add skills to your profile to see your match' : <>Skill match <b>{formatScore(j.match)}</b>{j.matched.length ? ` · ${j.matched.join(', ')}` : ''}</>}
                    </p>
                    <Link className="btn btn-primary btn-sm" to={`/apply/${j.job_id}`}>Apply</Link>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </Async>
  );
}
