import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../../api';
import { Async, EmptyState, PageHeader, useAsync } from '../../components/ui';
import { formatScore } from '../../utils/score';
import { ASSESSMENT_LABEL, formatDate } from '../../utils/status';

export default function Assessments() {
  const navigate = useNavigate();
  const state = useAsync(() => api.getMyApplications(), []);
  const [error, setError] = useState(null);

  // Starting happens on the assessment page, after the guide and the camera/microphone check.
  const take = (a) => {
    localStorage.setItem('hirelune_application_id', String(a.application_id));
    navigate(`/assessment?application=${a.application_id}`);
  };

  return (
    <>
      <PageHeader title="Assessments" subtitle="Each application has one assessment. It starts only when you click Take Assessment, and the timer runs on our server." />
      {error && <p className="alert alert-danger" role="alert">{error}</p>}
      <Async state={state} loadingLabel="Loading assessments…" errorLabel="Failed to load assessments">
        {(apps) => {
          const rows = apps.filter((a) => a.status !== 'rejected' || a.assessment_status === 'completed');
          if (!rows.length) return <EmptyState title="No assessments yet" action={<Link className="btn btn-primary btn-sm" to="/jobs">Browse jobs</Link>}>Apply to a job to unlock its assessment.</EmptyState>;
          return (
            <div className="card table-wrap">
              <table className="table" style={{ minWidth: 640 }}>
                <thead><tr><th scope="col">Role</th><th scope="col">Status</th><th scope="col">Completed</th><th scope="col">Test score</th><th scope="col">Action</th></tr></thead>
                <tbody>
                  {rows.map((a) => (
                    <tr key={a.application_id}>
                      <td><b>{a.job_title}</b><br /><span className="small muted">Applied {formatDate(a.applied_at)}</span></td>
                      <td><span className={`pill ${a.assessment_status === 'completed' ? 'pill-ok' : a.assessment_status === 'in_progress' ? 'pill-warn' : 'pill-neutral'}`}>{ASSESSMENT_LABEL[a.assessment_status]}</span></td>
                      <td>{formatDate(a.assessment_completed_at, true)}</td>
                      <td>{a.assessment_status === 'completed' ? formatScore(a.test_score) : '—'}</td>
                      <td>
                        {a.assessment_status === 'completed' && <Link className="btn btn-secondary btn-sm" to={`/assessment?application=${a.application_id}`}>View results</Link>}
                        {a.assessment_status === 'in_progress' && <Link className="btn btn-primary btn-sm" to={`/assessment?application=${a.application_id}`}>Continue Assessment</Link>}
                        {a.assessment_status === 'not_started' && <button className="btn btn-primary btn-sm" onClick={() => take(a)}>Take Assessment</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }}
      </Async>
    </>
  );
}
