import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { Async, EmptyState, PageHeader, useAsync } from '../../components/ui';
import { formatScore, scoreTone, compareScoresDesc } from '../../utils/score';

const COLUMNS = [
  ['screened', 'Screened', (a) => ['parsed', 'in_review', 'submitted'].includes(a.status) && a.assessment_status !== 'completed'],
  ['assessed', 'Assessed', (a) => a.status === 'assessed' || (a.assessment_status === 'completed' && ['parsed', 'in_review'].includes(a.status))],
  ['shortlisted', 'Shortlisted', (a) => a.status === 'shortlisted'],
  ['interview', 'Interview', (a) => ['scheduled', 'interviewed', 'selected'].includes(a.status)],
  ['offer', 'Offer', (a) => ['offered', 'offer_declined'].includes(a.status)],
  ['hired', 'Hired', (a) => a.status === 'hired'],
];

export default function HrCandidates() {
  const apps = useAsync(() => api.getCandidates(), []);
  const jobs = useAsync(() => api.getMyJobs(), []);
  const [jobId, setJobId] = useState('all');
  const scoped = useMemo(() => (apps.data || []).filter((a) => jobId === 'all' || String(a.job_id) === jobId), [apps.data, jobId]);
  return (
    <>
      <PageHeader title="Candidates" subtitle="Your talent pipeline by stage. Cards are sorted by final score (unscored last)."
                  actions={<select className="input" aria-label="Filter by role" style={{ width: 220 }} value={jobId} onChange={(e) => setJobId(e.target.value)}>
                    <option value="all">All roles</option>{(jobs.data || []).map((j) => <option key={j.job_id} value={String(j.job_id)}>{j.title}</option>)}
                  </select>} />
      <Async state={apps} loadingLabel="Loading candidates…" errorLabel="Failed to load candidates">
        {() => scoped.length === 0 ? <EmptyState title="No candidates yet">Candidates appear here once they apply to your roles.</EmptyState> : (
          <div className="board">
            {COLUMNS.map(([key, label, test]) => {
              const items = scoped.filter(test).sort((a, b) => compareScoresDesc(a.final_score, b.final_score) || compareScoresDesc(a.skill_score, b.skill_score));
              return (
                <section key={key} className="board-col" aria-label={`${label}: ${items.length}`}>
                  <h3 className="row" style={{ fontSize: 14 }}>{label}<span className="pill pill-neutral">{items.length}</span></h3>
                  {items.length === 0 && <p className="small muted">—</p>}
                  {items.map((a) => (
                    <Link key={a.application_id} to={`/hr/candidate/${a.candidate_id}`} className="board-card">
                      <b>{a.candidate_name}</b>
                      <span className="small muted">{a.job_title}</span>
                      <span className="small">Skill <b>{formatScore(a.skill_score)}</b> · Test <b>{formatScore(a.test_score)}</b></span>
                      <span className={`small tone-${scoreTone(a.final_score)}`}>Final <b>{formatScore(a.final_score)}</b>{a.status === 'offer_declined' ? ' · offer declined' : ''}</span>
                    </Link>
                  ))}
                </section>
              );
            })}
          </div>
        )}
      </Async>
      <p className="small muted" style={{ marginTop: 12 }}>Rejected candidates are listed under Applications → Rejected.</p>
    </>
  );
}
