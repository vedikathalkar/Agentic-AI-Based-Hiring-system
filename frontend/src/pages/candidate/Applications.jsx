import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ChevronDown } from 'lucide-react';
import HiringPipeline from '../../components/HiringPipeline';
import DecisionFeedback from '../../components/DecisionFeedback';
import StatusBadge from '../../components/StatusBadge';
import { api } from '../../api';
import { formatScore } from '../../utils/score';
import { applicationStageLabel, formatDate } from '../../utils/status';

export default function Applications() {
  const navigate = useNavigate();
  const [applications, setApplications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [openId, setOpenId] = useState(null);
  const load = () => {
    setLoading(true); setError(null);
    api.getMyApplications().then((rows) => {
      setApplications(rows);
      // A decision that ended the process opens its explanation straight away.
      const stopped = rows.find((a) => a.pipeline?.outcome?.state === 'stopped');
      setOpenId((cur) => cur ?? stopped?.application_id ?? null);
    }).catch((e) => setError(e.message)).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const open = (app) => {
    localStorage.setItem('hirelune_application_id', String(app.application_id));
    navigate(`/assessment?application=${app.application_id}`);
  };

  return (
    <div>
          <p className="eyebrow">Status</p>
          <h1 style={{ marginTop: 8, marginBottom: 24 }}>Your applications</h1>
          {loading && <p className="muted">Loading applications…</p>}
          {error && <p className="alert alert-danger" role="alert" style={{ marginBottom: 16 }}>Failed to load applications: {error} <button className="btn btn-secondary btn-sm" onClick={load}>Retry</button></p>}
          {!loading && !error && applications.length === 0 && (
            <div className="card" style={{ padding: 24 }}><p className="muted">No applications found.</p><button className="btn btn-primary" style={{ marginTop: 12 }} onClick={() => navigate('/jobs')}>Find jobs</button></div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {applications.map((app) => (
              <article key={app.application_id} className="card" style={{ padding: '22px 26px' }}>
                <div className="row" style={{ alignItems: 'flex-start', marginBottom: 16 }}>
                  <div>
                    <h3>{app.job_title || `Job #${app.job_id}`}</h3>
                    <p className="small muted" style={{ marginTop: 4 }}>Applied {formatDate(app.applied_at)}</p>
                  </div>
                  <span className="spacer" />
                  <StatusBadge label={applicationStageLabel(app)} />
                </div>
                <HiringPipeline pipeline={app.pipeline} />
                <dl className="kv" style={{ marginTop: 16 }}>
                  <dt>Skill score</dt><dd>{formatScore(app.skill_score)}</dd>
                  <dt>Experience score</dt><dd>{formatScore(app.experience_score)}</dd>
                  <dt>Test score</dt><dd>{app.assessment_status === 'completed' ? formatScore(app.test_score) : '—'}</dd>
                </dl>
                {app.screening_status === 'failed' && <p className="alert alert-warn small" style={{ marginTop: 12 }}>Screening could not be completed. You can still take the assessment.</p>}
                {app.has_resume === false && app.status !== 'rejected' && (
                  <p className="alert alert-warn small" style={{ marginTop: 12 }}>No resume is attached to this application yet, so it can't be screened.{' '}
                    <Link to={`/apply/${app.job_id}`}>Attach your resume</Link></p>
                )}
                <div className="row" style={{ marginTop: 16 }}>
                  {app.assessment_status === 'completed' && <button className="btn btn-secondary" onClick={() => open(app)}>View Assessment</button>}
                  {app.assessment_status === 'in_progress' && <button className="btn btn-primary" onClick={() => open(app)}>Continue Assessment</button>}
                  {app.assessment_status === 'not_started' && app.status !== 'rejected' && app.has_resume !== false && (
                    <button className="btn btn-primary" onClick={() => open(app)}>Take Assessment</button>
                  )}
                  <span className="spacer" />
                  <button className="btn btn-secondary" aria-expanded={openId === app.application_id} aria-controls={`why-${app.application_id}`}
                          onClick={() => setOpenId(openId === app.application_id ? null : app.application_id)}>
                    {app.pipeline?.outcome?.state === 'stopped' ? 'Why was I not selected?' : 'Where do I stand?'}
                    <ChevronDown size={16} aria-hidden="true" style={{ transform: openId === app.application_id ? 'rotate(180deg)' : 'none', transition: 'transform .25s' }} />
                  </button>
                </div>
                {openId === app.application_id && (
                  <div id={`why-${app.application_id}`} style={{ marginTop: 18, paddingTop: 18, borderTop: '1px solid var(--ink-100)' }}>
                    <DecisionFeedback applicationId={app.application_id} showPipeline={false} />
                  </div>
                )}
              </article>
            ))}
          </div>
    </div>
  );
}
